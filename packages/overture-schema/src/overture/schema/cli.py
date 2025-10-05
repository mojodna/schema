"""Click-based CLI for overture-schema package."""

import inspect
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated as AnnotatedType
from typing import Any, Literal, get_args, get_origin

import click
import yaml
from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from rich.console import Console
from rich.text import Text
from yamlcore import CoreLoader  # type: ignore

from overture.schema import create_union_from_models
from overture.schema.core.discovery import ModelKey, discover_models
from overture.schema.core.json_schema import json_schema
from overture.schema.core.parser import validate_feature, validate_features

# Create a console instances for rich output
stdout = Console(highlight=False)
stderr = Console(highlight=False, file=sys.stderr)


def create_union_type_from_models(
    models: dict[ModelKey, type],
) -> Any:  # noqa: ANN401
    """Create a discriminated union type from a dict of models.

    Args:
        models: Dict mapping ModelKey to Pydantic model classes

    Returns:
        Annotated union type suitable for parse_feature
    """
    return create_union_from_models(list(models.values()))


def resolve_types(
    use_overture_types: bool,
    namespace: str | None,
    theme_names: tuple[str, ...],
    type_names: tuple[str, ...],
) -> Any:  # noqa: ANN401
    """Resolve CLI options into a model type suitable for parse_feature.

    Args:
        use_overture_types: Boolean from --overture-types flag
        namespace: Namespace to filter by (e.g., "overture", "annex")
        theme_names: List of theme names from --theme option
        type_names: List of type names from --type option

    Returns:
        Model type suitable for passing to parse_feature
    """
    # Discover all available models via entry points
    all_models = discover_models(namespace=namespace)

    # Filter models based on CLI options
    filtered_models = {}

    if use_overture_types:
        # Use only official Overture types (namespace="overture")
        filtered_models = discover_models(namespace="overture")

    elif theme_names and not type_names:
        # Theme-only mode: all types in specified themes
        for key, model_class in all_models.items():
            if key.theme in theme_names:
                filtered_models[key] = model_class

    elif type_names and not theme_names:
        # Type-only mode: find matching types across all themes
        for key, model_class in all_models.items():
            if key.type in type_names:
                filtered_models[key] = model_class

    elif type_names and theme_names:
        # Both specified: find matching types within specified themes
        for key, model_class in all_models.items():
            if key.theme in theme_names and key.type in type_names:
                filtered_models[key] = model_class

    else:
        # No filters specified - use all models
        filtered_models = all_models

    if not filtered_models:
        raise ValueError("No models found matching the specified criteria")

    return create_union_type_from_models(filtered_models)


# Type aliases for structural tuple elements
StructuralElement = Literal["list_index", "union", "model", "discriminator", "field"]


@dataclass
class UnionMetadata:
    """Metadata about a union type's structure."""

    is_discriminated: bool
    discriminator_field: str | None
    # Map discriminator values to their corresponding model types
    discriminator_to_model: dict[str, type[BaseModel]]
    # Map model class names to their types (for non-discriminated unions)
    model_name_to_model: dict[str, type[BaseModel]]
    # Nested union metadata for union members that are themselves unions
    nested_unions: dict[str, "UnionMetadata"]


def introspect_union(union_type: Any) -> UnionMetadata:  # noqa: ANN401
    """Introspect a union type to extract structural information.

    Args:
        union_type: A union type (may be Annotated with discriminator)

    Returns:
        UnionMetadata describing the structure of the union
    """
    # Check if this is a list type - unwrap to get the element type
    origin = get_origin(union_type)
    if origin is list:
        args = get_args(union_type)
        if args:
            # Recursively introspect the list element type
            return introspect_union(args[0])

    # Check if this is an Annotated type with a discriminator
    discriminator_field = None
    actual_union = union_type

    # Unwrap Annotated ONLY if the top level is Annotated
    if origin is AnnotatedType:
        # This is Annotated[Union[...], ...]
        args = get_args(union_type)
        if args:
            # First arg is the actual type, rest are metadata
            actual_union = args[0]
            # Look for Field with discriminator in metadata
            for metadata in args[1:]:
                if isinstance(metadata, FieldInfo) and hasattr(
                    metadata, "discriminator"
                ):
                    discriminator_field = metadata.discriminator
                    break

    # Get union members
    union_origin = get_origin(actual_union)
    if union_origin is None:
        # Not a union, might be a single model
        union_members = [actual_union]
    else:
        union_members = list(get_args(actual_union))

    discriminator_to_model: dict[str, type[BaseModel]] = {}
    model_name_to_model: dict[str, type[BaseModel]] = {}
    nested_unions: dict[str, UnionMetadata] = {}

    # Analyze each union member
    for member in union_members:
        # Check if member is itself annotated (nested discriminated union)
        member_origin = get_origin(member)

        # If it's an Annotated type, it might contain a discriminated union
        if member_origin is AnnotatedType:
            # Check if this is an Annotated with a discriminator
            member_args = get_args(member)
            if member_args:
                # Check for Field with discriminator in the annotations
                has_discriminator = False
                for metadata in member_args[1:]:
                    if isinstance(metadata, FieldInfo) and hasattr(
                        metadata, "discriminator"
                    ):
                        has_discriminator = True
                        break

                if has_discriminator:
                    # This is a nested discriminated union
                    nested_metadata = introspect_union(member)
                    nested_unions[str(member)] = nested_metadata
                    # Also extract discriminator mappings from the nested union
                    discriminator_to_model.update(
                        nested_metadata.discriminator_to_model
                    )
                    continue

                # Check if the inner type is a union (could be Union without Annotated)
                inner_type = member_args[0]
                if get_origin(inner_type) is not None:
                    # Nested union without discriminator at this level
                    nested_metadata = introspect_union(member)
                    nested_unions[str(member)] = nested_metadata
                    discriminator_to_model.update(
                        nested_metadata.discriminator_to_model
                    )
                    continue

        # It's a BaseModel
        if inspect.isclass(member) and issubclass(member, BaseModel):
            model_name_to_model[member.__name__] = member

            # Extract discriminator values from ALL Literal fields (not just the current discriminator)
            # This handles nested discriminators with different field names
            for _field_name, field_info in member.model_fields.items():
                annotation = field_info.annotation
                literal_origin = get_origin(annotation)
                if literal_origin is Literal:
                    literal_args = get_args(annotation)
                    if literal_args:
                        disc_value = literal_args[0]
                        discriminator_to_model[disc_value] = member

    return UnionMetadata(
        is_discriminated=discriminator_field is not None,
        discriminator_field=discriminator_field,
        discriminator_to_model=discriminator_to_model,
        model_name_to_model=model_name_to_model,
        nested_unions=nested_unions,
    )


def create_structural_tuple(
    loc: tuple[str | int, ...],
    union_type: Any,  # noqa: ANN401
) -> tuple[StructuralElement, ...]:
    """Create a structural tuple parallel to error['loc'] describing each element.

    Args:
        loc: The location tuple from a Pydantic validation error
        union_type: The union type being validated against

    Returns:
        Tuple of same length as loc with structural labels for each element
    """
    metadata = introspect_union(union_type)
    structural: list[StructuralElement] = []

    i = 0
    while i < len(loc):
        element = loc[i]

        # Check if it's a list index (integer)
        if isinstance(element, int):
            structural.append("list_index")
            i += 1
            continue

        # Check if it's a union marker string
        if isinstance(element, str) and element.startswith("tagged-union["):
            structural.append("union")
            i += 1
            # After a union marker, expect discriminator value(s)
            # Continue to identify following discriminator elements
            continue

        # Check if it's a model class name (non-discriminated union member)
        if isinstance(element, str) and element in metadata.model_name_to_model:
            structural.append("model")
            i += 1
            continue

        # Check if it's a discriminator value (can come from nested unions)
        if isinstance(element, str) and element in metadata.discriminator_to_model:
            structural.append("discriminator")
            i += 1
            # After discriminator, might have more discriminators (nested) or fields
            # Check if the selected model has nested unions
            selected_model = metadata.discriminator_to_model[element]
            # For now, assume next elements are either more discriminators or fields
            continue

        # Otherwise, it's a field name
        structural.append("field")
        i += 1

    return tuple(structural)


def extract_discriminator_path(
    loc: tuple[str | int, ...],
    structural: tuple[StructuralElement, ...],
) -> tuple[str | int, ...]:
    """Extract the discriminator path from a location tuple.

    The discriminator path includes union markers, model names, and discriminator
    values - everything up to (but not including) the first field. List indices are
    excluded to prevent false ambiguity when validating lists of features.

    Args:
        loc: The location tuple from a Pydantic validation error
        structural: The parallel structural tuple

    Returns:
        The discriminator path portion of the location tuple (excluding list_index)
    """
    discriminator_path = []
    for element, struct_type in zip(loc, structural, strict=False):
        if struct_type == "field":
            # Stop at the first field
            break
        if struct_type != "list_index":
            # Include everything except list indices
            discriminator_path.append(element)
    return tuple(discriminator_path)


def group_errors_by_discriminator(
    errors: list[dict[str, Any]],
    model_type: Any,  # noqa: ANN401
) -> dict[tuple[str | int, ...], list[dict[str, Any]]]:
    """Group validation errors by their discriminator path.

    Args:
        errors: List of Pydantic validation error dicts
        model_type: The union type being validated against

    Returns:
        Dictionary mapping discriminator paths to lists of errors
    """
    groups: dict[tuple[str | int, ...], list[dict[str, Any]]] = {}

    for error in errors:
        loc = error["loc"]
        try:
            structural = create_structural_tuple(loc, model_type)
            disc_path = extract_discriminator_path(loc, structural)
            if disc_path not in groups:
                groups[disc_path] = []
            groups[disc_path].append(error)
        except Exception:
            # If structural analysis fails, group under empty path
            if () not in groups:
                groups[()] = []
            groups[()].append(error)

    return groups


def select_most_likely_errors(
    error_groups: dict[tuple[str | int, ...], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], bool]:
    """Select the error group(s) most likely to be the intended model.

    Uses heuristic: the group with the fewest errors is most likely correct,
    as it requires the fewest changes to make the data valid.

    When multiple groups have the same minimum error count (a tie), returns
    all tied groups to indicate ambiguity to the user.

    Args:
        error_groups: Dictionary mapping discriminator paths to error lists

    Returns:
        Tuple of (errors_list, is_tied) where:
        - errors_list: Flattened list of errors from all tied groups
        - is_tied: True if multiple groups had the same minimum error count
    """
    if not error_groups:
        return [], False

    # Find the minimum error count
    min_error_count = min(len(errors) for errors in error_groups.values())

    # Get all groups with the minimum error count
    tied_groups = [
        errors for errors in error_groups.values() if len(errors) == min_error_count
    ]

    # Flatten all errors from tied groups
    all_errors = [error for group in tied_groups for error in group]

    # Indicate if there was a tie
    is_tied = len(tied_groups) > 1

    return all_errors, is_tied


@click.group()
@click.version_option(package_name="overture-schema")
def cli() -> None:
    """Overture Schema command-line interface."""
    pass


def flatten_geojson(_feature: dict[str, Any]) -> dict[str, Any]:
    """Create a variant of the feature with flat/Parquet-style structure.

    Args:
        feature: Feature dict in GeoJSON or flat format

    Returns:
        Feature dict in flat format
    """
    feature = _feature.copy()

    # Check if this is GeoJSON format that needs flattening
    if "properties" in feature and feature.get("type") == "Feature":
        # Flatten GeoJSON feature to match GeoParquet structure
        feature.update(feature["properties"])
        del feature["properties"]
        # Remove the GeoJSON "type": "Feature" field
        if feature.get("type") == "Feature":
            del feature["type"]

    return feature


def format_path(filtered_loc: list[str | int]) -> str:
    """Convert filtered location path to dot-separated string.

    Args:
        filtered_loc: List of path components (strings and integers)

    Returns:
        Formatted path string (e.g., "properties.name" or "items[0].value")
    """
    path_str = ""
    for i, part in enumerate(filtered_loc):
        if isinstance(part, str):
            if i > 0:
                path_str += "."
            path_str += part
        else:
            path_str += f"[{part}]"

    if not path_str:
        path_str = "(root)"

    return path_str


def format_validation_error(
    error: Any,
    console: Console,
    model_type: Any = None,  # noqa: ANN401
    show_model_hint: bool = False,
) -> None:
    """Format and print a single validation error.

    Args:
        error: Pydantic validation error dict
        console: Rich Console instance for output
        model_type: The union type being validated against (optional)
        show_model_hint: Show which model was selected for validation (first error only)

    TODO: Add optional Rich Table display for errors (--show-table flag)
        - Show the feature data that failed validation
        - Highlight the problematic fields
        - Makes debugging easier for lists of features

    TODO: Use error path to navigate back into original input data
        - Parse error path (e.g., [1].properties.name)
        - Navigate to that location in original input
        - Detect and drop discriminator elements (like tagged-union[...])
        - Extract exact problematic value from original input
        - Reuse this logic for Rich Table highlighting
        - Improves error messages with precise context
    """
    loc = error["loc"]

    # Determine which model was selected for this error
    selected_model = None
    if model_type is not None and show_model_hint:
        try:
            metadata = introspect_union(model_type)
            structural = create_structural_tuple(loc, model_type)

            # Look for discriminator value in the location path
            for element, struct_type in zip(loc, structural, strict=False):
                if struct_type == "discriminator" and isinstance(element, str):
                    selected_model = metadata.discriminator_to_model.get(element)
                    break
                elif struct_type == "model" and isinstance(element, str):
                    selected_model = metadata.model_name_to_model.get(element)
                    break
        except Exception:
            pass

    # Filter out union markers from the path using structural analysis
    if model_type is not None:
        try:
            structural = create_structural_tuple(loc, model_type)
            # Filter out 'union', 'model', and 'discriminator' markers
            # Keep only 'list_index' and 'field' elements for display
            filtered_loc = [
                element
                for element, struct_type in zip(loc, structural, strict=False)
                if struct_type in ("list_index", "field")
            ]
        except Exception:
            # Fall back to original loc if structural analysis fails
            filtered_loc = list(loc)
    else:
        filtered_loc = list(loc)

    # Convert to dot-separated path
    path_str = format_path(filtered_loc)

    # Show model hint if this is the first error in a group
    if selected_model is not None:
        model_name = selected_model.__name__
        console.print(f"  [dim]Probable type:[/dim] {model_name}", style="blue")
        console.print()

    # Format the error message
    msg = error["msg"]
    input_value = error.get("input")

    ctx = error.get("ctx", {})
    if "error" in ctx:
        msg = ctx["error"]
        input_value = None

    console.print(f"  {path_str}", style="cyan")
    console.print(f"    → {msg}", style="yellow")

    # Show input value if present and not too large
    if input_value is not None:
        value_str = (
            repr(input_value)
            if not isinstance(input_value, str)
            else f"'{input_value}'"
        )
        prefix = "    → Got: "
        if len(value_str) <= console.width - len(prefix):
            console.print(f"{prefix}{value_str}", style="dim")
    console.print()


@cli.command()
@click.argument("filename", type=click.Path(path_type=Path), required=False)
@click.option(
    "--overture-types",
    is_flag=True,
    help="Validate against all official Overture types (excludes extensions)",
)
@click.option(
    "--namespace",
    help="Namespace to filter by (e.g., overture, annex)",
)
@click.option(
    "--theme",
    multiple=True,
    help="Theme to validate against (shorthand for all types in theme)",
)
@click.option(
    "--type",
    multiple=True,
    help="Specific type to validate against (e.g., building, segment)",
)
def validate(
    filename: Path | None,
    overture_types: bool,
    namespace: str | None,
    theme: tuple[str, ...],
    type: tuple[str, ...],
) -> None:
    """Validate Overture Maps data against schemas.

    Read from FILENAME or stdin if FILENAME is '-' or not provided.
    """
    # Determine input source
    use_stdin = filename is None or str(filename) == "-"
    source_name = "<stdin>" if use_stdin else str(filename)

    if not use_stdin and not filename.is_file():
        stderr.print(f"Error: '{filename}' is not a file.")
        sys.exit(1)

    try:
        model_type = resolve_types(overture_types, namespace, theme, type)

        # Read and parse the YAML/JSON input
        # Use YAML-1.2-compliant loader (YAML-1.2 dropped support for yes/no boolean values)
        if use_stdin:
            data = yaml.load(sys.stdin, Loader=CoreLoader)
        else:
            with filename.open("r", encoding="utf-8") as f:
                data = yaml.load(f, Loader=CoreLoader)

        # Validate based on input type
        if isinstance(data, list):
            # List of features
            validate_features(data, model_type)
        elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
            # GeoJSON FeatureCollection
            validate_features(data["features"], model_type)
        else:
            # Single feature
            validate_feature(data, model_type)

        stdout.print(f"✓ Successfully validated {source_name}")

    except yaml.YAMLError as e:
        stderr.print(f"Error: '{source_name}' contains invalid input: {e}")
        sys.exit(1)

    except ValidationError as e:
        stderr.print("Validation failed:", style="red")
        stderr.print()

        # Group errors by discriminator path and select most likely group(s)
        error_groups = group_errors_by_discriminator(e.errors(), model_type)
        filtered_errors, is_tied = select_most_likely_errors(error_groups)

        # Show tie indicator if multiple groups had same error count
        if is_tied:
            stderr.print(
                "  ⚠ Ambiguous: multiple possible interpretations with equal error counts",
                style="yellow dim",
            )
            stderr.print()

        # Display the most likely errors
        for i, error in enumerate(filtered_errors):
            # Show model hint only for the first error
            format_validation_error(error, stderr, model_type, show_model_hint=(i == 0))

        sys.exit(1)

    except Exception as e:
        stderr.print(f"Error: Unexpected error processing '{source_name}': {e}")
        sys.exit(1)


@cli.command("json-schema")
@click.option(
    "--overture-types",
    is_flag=True,
    help="Generate schema for all official Overture types (excludes extensions)",
)
@click.option(
    "--namespace",
    help="Namespace to filter by (e.g., overture, annex)",
)
@click.option(
    "--theme",
    multiple=True,
    help="Theme to generate schema for (shorthand for all types in theme)",
)
@click.option(
    "--type",
    multiple=True,
    help="Specific type to generate schema for (e.g., building, segment)",
)
def json_schema_command(
    overture_types: bool,
    namespace: str | None,
    theme: tuple[str, ...],
    type: tuple[str, ...],
) -> None:
    """Generate JSON schema for Overture Maps types."""
    try:
        model_type = resolve_types(overture_types, namespace, theme, type)
        schema = json_schema(model_type)
        # Use plain print for JSON output to avoid Rich formatting
        print(json.dumps(schema, indent=2, sort_keys=True))
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
    except Exception as e:
        click.echo(f"Error generating JSON schema: {e}", err=True)


def get_theme_module_docstring(theme_name: str) -> str | None:
    """Get the docstring of a theme module if available."""
    try:
        # Try to import the theme module
        module_name = f"overture.schema.{theme_name}"
        module = __import__(module_name, fromlist=[""])
        return inspect.getdoc(module)
    except (ImportError, AttributeError):
        return None


def get_model_docstring(model_class: type[BaseModel]) -> str | None:
    """Get a clean, formatted docstring from a model class."""
    return inspect.getdoc(model_class)


def rewrap(text: str, console: Console, indent: int = 0, padding_right: int = 0) -> str:
    """Unwrap and re-wrap text at console width with indentation.

    Args:
        text: The text to rewrap
        console: Rich Console instance for width and wrapping
        indent: Number of spaces to indent (default: 0)
        padding_right: Right padding to subtract from width (default: 0)

    Returns:
        Re-wrapped and indented text
    """
    unwrapped = " ".join(text.split())
    text_obj = Text(unwrapped)
    wrapped_lines = text_obj.wrap(console, console.width - indent - padding_right)
    return "\n".join(f"{' ' * indent}{line}" for line in wrapped_lines)


def dump_namespace(
    theme_types: dict[str | None, list[tuple[ModelKey, type[BaseModel]]]],
) -> None:
    """Print all themes and types for a namespace.

    Args:
        namespace: Namespace name
        theme_types: Dict mapping theme to list of (ModelKey, model_class) tuples
    """
    for theme in sorted(theme_types.keys(), key=lambda x: (x is None, x)):
        if theme:
            stdout.print(
                f"[bold green underline]{theme.upper()}[/bold green underline]"
            )

            theme_docstring = get_theme_module_docstring(theme)
            if theme_docstring:
                stdout.print(
                    rewrap(theme_docstring, stdout, padding_right=4), style="dim"
                )

            stdout.print()

        # Add types to the tree
        sorted_types = sorted(theme_types[theme], key=lambda x: x[0].type)
        for key, model_class in sorted_types:
            stdout.print(
                f"  [bright_black]→[/bright_black] [bold cyan]{key.type}[/bold cyan] [dim magenta]({key.class_name})[/dim magenta]"
            )
            docstring = get_model_docstring(model_class)
            if docstring:
                stdout.print(
                    rewrap(docstring, stdout, indent=4, padding_right=12), style="dim"
                )
            stdout.print()


@cli.command("list-types")
def list_types() -> None:
    """List all available types grouped by theme with descriptions."""
    try:
        models = discover_models()

        # Group models by namespace and theme
        namespaces: dict[
            str, dict[str | None, list[tuple[ModelKey, type[BaseModel]]]]
        ] = {}
        for key, model_class in models.items():
            if key.namespace not in namespaces:
                namespaces[key.namespace] = {}
            if key.theme not in namespaces[key.namespace]:
                namespaces[key.namespace][key.theme] = []

            namespaces[key.namespace][key.theme].append((key, model_class))

        # display Overture themes first
        if "overture" in namespaces:
            stdout.print("[bold red]OVERTURE THEMES[/bold red]", justify="center")
            stdout.print()

            dump_namespace(namespaces["overture"])

            stdout.print("[bold red]ADDITIONAL TYPES[/bold red]", justify="center")
            stdout.print()

        for namespace in sorted(namespaces.keys()):
            if namespace == "overture":
                continue

            stdout.print(f"[bold blue]{namespace.upper()}[/bold blue]")
            dump_namespace(namespaces[namespace])

    except Exception as e:
        click.echo(f"Error listing types: {e}", err=True)


if __name__ == "__main__":
    cli()
