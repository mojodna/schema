"""Click-based CLI for overture-schema package."""

import builtins
import json
import sys
from collections import Counter
from pathlib import Path

import click
import yaml
from pydantic import BaseModel, ValidationError
from rich.console import Console
from yamlcore import CoreLoader  # type: ignore

from overture.schema import create_union_from_models
from overture.schema.core.discovery import ModelKey, discover_models
from overture.schema.core.json_schema import json_schema
from overture.schema.core.parser import validate_feature, validate_features

from .docstrings import get_model_docstring, get_theme_module_docstring
from .error_formatting import (
    format_validation_error,
    group_errors_by_discriminator,
    select_most_likely_errors,
)
from .output import rewrap
from .type_analysis import StructuralTuple, get_item_index, introspect_union
from .types import ErrorLocation, ModelDict, UnionType

# Create a console instances for rich output
stdout = Console(highlight=False)
stderr = Console(highlight=False, file=sys.stderr)


def create_union_type_from_models(
    models: ModelDict,
) -> UnionType:
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
) -> UnionType:
    """Resolve CLI options into a model type suitable for parse_feature.

    Args:
        use_overture_types: Boolean from --overture-types flag
        namespace: Namespace to filter by (e.g., "overture", "annex")
        theme_names: List of theme names from --theme option
        type_names: List of type names from --type option

    Returns:
        Model type suitable for passing to parse_feature
    """
    # Determine effective namespace
    effective_namespace = "overture" if use_overture_types else namespace

    # Discover models once with the appropriate namespace
    all_models = discover_models(namespace=effective_namespace)

    # Filter models based on CLI options
    filtered_models: ModelDict = {}

    if use_overture_types:
        filtered_models = all_models

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


def get_source_name(filename: Path) -> str:
    """Get display name for input source.

    Args:
        filename: Path to input file or "-" for stdin

    Returns:
        Display name: "<stdin>" for stdin input, otherwise the filename
    """
    return "<stdin>" if str(filename) == "-" else str(filename)


@click.group()
@click.version_option(package_name="overture-schema")
def cli() -> None:
    """Overture Schema command-line interface.

    Provides validation, schema generation, and type discovery for Overture Maps data.

    \b
    Examples:
      # Validate a file
      $ overture-schema validate data.json
    \b
      # Validate from stdin
      $ overture-schema validate - < data.json
    \b
      # List available types
      $ overture-schema list-types
    \b
      # Generate JSON schema
      $ overture-schema json-schema --theme buildings
    \b
      # Validate specific types
      $ overture-schema validate --theme buildings data.json
    """
    pass


def load_input(filename: Path) -> tuple[dict | list, str]:
    """Load and parse input from file or stdin.

    Args:
        filename: Path to input file, or "-" for stdin

    Returns:
        Tuple of (parsed_data, source_name)

    Raises:
        yaml.YAMLError: If input is invalid YAML/JSON
        SystemExit: If filename doesn't exist or isn't a file
    """
    if str(filename) == "-":
        # Read all stdin content
        content = sys.stdin.read()

        # Try to detect JSONL format (newline-delimited JSON)
        # JSONL has multiple non-empty lines, each containing a complete JSON object
        lines = [line.strip() for line in content.strip().split("\n") if line.strip()]

        if len(lines) > 1:
            # Attempt to parse as JSONL
            try:
                parsed_lines = [json.loads(line) for line in lines]
                return parsed_lines, "<stdin>"
            except json.JSONDecodeError:
                # Not valid JSONL, fall through to YAML parser
                pass

        # Parse as single YAML/JSON document
        import io

        data = yaml.load(io.StringIO(content), Loader=CoreLoader)
        return data, "<stdin>"

    if not filename.is_file():
        raise click.UsageError(f"'{filename}' is not a file.")

    # Warn about unexpected file extensions
    if filename.suffix not in {".json", ".yaml", ".yml", ".geojson"}:
        click.echo(
            f"Warning: File '{filename}' has unexpected extension. "
            f"Expecting .json, .yaml, .yml, or .geojson",
            err=True,
        )

    # Use YAML-1.2-compliant loader (YAML-1.2 dropped support for yes/no boolean values)
    with filename.open("r", encoding="utf-8") as f:
        data = yaml.load(f, Loader=CoreLoader)

    return data, str(filename)


def perform_validation(data: dict | list, model_type: UnionType) -> None:
    """Validate data based on its structure.

    Automatically detects and handles three input formats:
    - Single feature (dict)
    - List of features (list)
    - GeoJSON FeatureCollection (dict with type="FeatureCollection")

    Args:
        data: Parsed data to validate
        model_type: Union type for validation

    Raises:
        ValidationError: If validation fails
    """
    if isinstance(data, list):
        # List of features
        validate_features(data, model_type)
    elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
        # GeoJSON FeatureCollection
        validate_features(data["features"], model_type)
    else:
        # Single feature
        validate_feature(data, model_type)


def compute_collection_statistics(
    item_types: dict[int, builtins.type[BaseModel] | None],
    filtered_errors: list,
) -> tuple[
    int,
    Counter[builtins.type[BaseModel] | None],
    dict[builtins.type[BaseModel], set[int]],
]:
    """Compute validation statistics for heterogeneous collections.

    Args:
        item_types: Mapping from item index to detected model type
        filtered_errors: List of filtered validation errors

    Returns:
        Tuple of (items_without_errors, type_counts, items_with_errors_by_type)
    """
    # Compute statistics: group items by type
    type_counts: Counter[builtins.type[BaseModel] | None] = Counter(item_types.values())

    # Determine total number of items (max index + 1, or count from data)
    max_index = max(item_types.keys()) if item_types else -1
    total_items = max_index + 1

    # Count items with errors per type
    items_with_errors_by_type: dict[builtins.type[BaseModel], set[int]] = {}
    for err in filtered_errors:
        idx = get_item_index(err["loc"])
        if idx is not None and idx in item_types:
            model_type_cls = item_types[idx]
            if model_type_cls is not None:
                if model_type_cls not in items_with_errors_by_type:
                    items_with_errors_by_type[model_type_cls] = set()
                items_with_errors_by_type[model_type_cls].add(idx)

    # Count items without any errors
    items_without_errors = total_items - len(
        {
            idx
            for idx in item_types.keys()
            if any(get_item_index(err["loc"]) == idx for err in filtered_errors)
        }
    )

    return items_without_errors, type_counts, items_with_errors_by_type


def print_collection_statistics(
    items_without_errors: int,
    type_counts: Counter[builtins.type[BaseModel] | None],
    items_with_errors_by_type: dict[builtins.type[BaseModel], set[int]],
    stderr: Console,
) -> None:
    """Print validation statistics for heterogeneous collections.

    Args:
        items_without_errors: Count of items with no validation errors
        type_counts: Counter of items by model type
        items_with_errors_by_type: Mapping from model type to set of item indices with errors
        stderr: Console for stderr output
    """
    stderr.print("  [dim]Collection statistics:[/dim]")

    # Show items without errors first
    # TODO: Once we switch to parse_features (instead of validate_features),
    # we can include type information for items without errors by parsing
    # the input and tracking which items validated successfully and their types.
    # This would allow output like: "Building: 2 confirmed (no errors)"
    if items_without_errors > 0:
        stderr.print(
            f"    • {items_without_errors} item{'s' if items_without_errors != 1 else ''} with no errors",
            style="dim",
        )

    # Show per-type statistics
    for model_type_cls, count in type_counts.most_common():
        if model_type_cls is not None:
            items_with_errors = len(
                items_with_errors_by_type.get(model_type_cls, set())
            )
            valid_count = count - items_with_errors

            if valid_count > 0:
                stderr.print(
                    f"    • {model_type_cls.__name__}: {valid_count} confirmed, {items_with_errors} with errors",
                    style="dim",
                )
            else:
                stderr.print(
                    f"    • {model_type_cls.__name__} (probable): {items_with_errors} item{'s' if items_with_errors != 1 else ''} with errors",
                    style="dim",
                )
    stderr.print()


def handle_validation_error(
    e: ValidationError,
    model_type: UnionType,
    stderr: Console,
    original_data: dict | list | None = None,
) -> None:
    """Handle and format validation errors with rich contextual information.

    Groups errors by discriminator, selects most likely error groups, and provides
    helpful diagnostics for heterogeneous collections and ambiguous types.

    Args:
        e: ValidationError from pydantic
        model_type: Union type used for validation
        stderr: Console for stderr output
        original_data: Original input data for error display
    """
    # Compute metadata once upfront
    metadata = introspect_union(model_type)

    # Create cache for structural tuple computation (optimizes systematic errors)
    structural_cache: dict[ErrorLocation, StructuralTuple] = {}

    # Group errors by discriminator path and select most likely group(s)
    error_groups = group_errors_by_discriminator(e.errors(), metadata, structural_cache)
    filtered_errors, is_tied, is_heterogeneous, item_types = select_most_likely_errors(
        error_groups,
        metadata=metadata,
        all_errors=e.errors(),
        structural_cache=structural_cache,
    )

    # Show heterogeneity warning if collection has mixed types
    if is_heterogeneous:
        stderr.print(
            "  ⚠ Heterogeneous collection: Data contains multiple feature types.",
            style="yellow",
        )
        stderr.print(
            "    • Consider validating each type separately with --theme or --type",
            style="dim",
        )
        stderr.print()

        # Compute and display statistics if there are errors to report
        if filtered_errors:
            items_without_errors, type_counts, items_with_errors_by_type = (
                compute_collection_statistics(item_types, filtered_errors)
            )
            print_collection_statistics(
                items_without_errors, type_counts, items_with_errors_by_type, stderr
            )

    # Show tie indicator if multiple groups had same error count
    elif is_tied:
        stderr.print(
            "  ⚠ Ambiguous: Data matches multiple types equally. Consider:",
            style="yellow",
        )
        stderr.print(
            "    • Specifying --theme or --type to narrow validation", style="dim"
        )
        stderr.print("    • Adding discriminator fields to clarify intent", style="dim")
        stderr.print()

    # Group errors by item
    from collections import defaultdict

    errors_by_item: dict[int | None, list] = defaultdict(list)
    for error in filtered_errors:
        item_idx = get_item_index(error["loc"])
        errors_by_item[item_idx].append(error)

    # Display errors grouped by item
    from .error_formatting import format_validation_errors_verbose

    for item_idx, item_errors in errors_by_item.items():
        # Determine item type
        error_item_type = None
        if item_idx is not None and item_idx in item_types:
            error_item_type = item_types.get(item_idx)

        # Try verbose display first
        displayed = format_validation_errors_verbose(
            item_errors,
            stderr,
            metadata=metadata,
            item_type=error_item_type,
            structural_cache=structural_cache,
            original_data=original_data,
            item_index=item_idx,
        )

        # Fall back to non-verbose format if verbose couldn't display
        if not displayed:
            for i, error in enumerate(item_errors):
                format_validation_error(
                    error,
                    stderr,
                    metadata=metadata,
                    show_model_hint=(i == 0),
                    item_type=error_item_type,
                    show_item_type=is_heterogeneous,
                    structural_cache=structural_cache,
                    original_data=original_data,
                    show_feature_data=False,
                )


def handle_generic_error(e: Exception, filename: Path, error_type: str) -> None:
    """Handle generic errors during validation.

    Args:
        e: Exception that occurred
        filename: Input filename or "-" for stdin
        error_type: Type of error for user-friendly message

    Raises:
        click.UsageError: Always, with formatted error message
    """
    source_name = get_source_name(filename)

    if error_type == "yaml":
        raise click.UsageError(f"'{source_name}' contains invalid input: {e}")
    elif error_type == "value":
        raise click.UsageError(str(e))
    elif error_type == "key":
        raise click.UsageError(f"Invalid data structure - missing key: {e}")
    else:
        raise click.UsageError(f"Error processing {source_name}: {e}")


@cli.command()
@click.argument("filename", type=click.Path(path_type=Path), required=True)
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
    "types",
    multiple=True,
    help="Specific type to validate against (e.g., building, segment)",
)
def validate(
    filename: Path,
    overture_types: bool,
    namespace: str | None,
    theme: tuple[str, ...],
    types: tuple[str, ...],
) -> None:
    """Validate Overture Maps data against schemas.

    Read from FILENAME or stdin if FILENAME is '-'.
    Supports JSON, YAML, and GeoJSON formats.

    \b
    Examples:
      # Validate a file
      $ overture-schema validate data.json
    \b
      # Validate from stdin
      $ overture-schema validate - < data.json
    \b
      # Validate only buildings
      $ overture-schema validate --theme buildings data.json
    \b
      # Validate specific type
      $ overture-schema validate --type building data.json
    \b
      # Official Overture types only
      $ overture-schema validate --overture-types data.json
    """
    try:
        model_type = resolve_types(overture_types, namespace, theme, types)
        data, source_name = load_input(filename)
        perform_validation(data, model_type)
        stdout.print(f"✓ Successfully validated {source_name}")
    except yaml.YAMLError as e:
        handle_generic_error(e, filename, "yaml")
    except ValidationError as e:
        handle_validation_error(e, model_type, stderr, original_data=data)
        sys.exit(1)
    except ValueError as e:
        handle_generic_error(e, filename, "value")
    except KeyError as e:
        handle_generic_error(e, filename, "key")


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
    "types",
    multiple=True,
    help="Specific type to generate schema for (e.g., building, segment)",
)
def json_schema_command(
    overture_types: bool,
    namespace: str | None,
    theme: tuple[str, ...],
    types: tuple[str, ...],
) -> None:
    """Generate JSON schema for Overture Maps types.

    Outputs a JSON Schema document to stdout that can be used for validation
    or documentation purposes.

    \b
    Examples:
      # All types
      $ overture-schema json-schema > schema.json
    \b
      # Buildings theme
      $ overture-schema json-schema --theme buildings
    \b
      # Specific types
      $ overture-schema json-schema --type building
    \b
      # Official Overture types only
      $ overture-schema json-schema --overture-types
    """
    try:
        model_type = resolve_types(overture_types, namespace, theme, types)
        schema = json_schema(model_type)
        # Use plain print for JSON output to avoid Rich formatting
        print(json.dumps(schema, indent=2, sort_keys=True))
    except ValueError as e:
        raise click.UsageError(str(e)) from e


def dump_namespace(
    theme_types: dict[str | None, list[tuple[ModelKey, type[BaseModel]]]],
) -> None:
    """Print all themes and types for a namespace.

    Displays themes in alphabetical order with their types and docstrings.
    Each type includes its model class name and description.

    Args:
        theme_types: Dict mapping theme name to list of (ModelKey, model_class) tuples
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
    """List all available types grouped by theme with descriptions.

    Displays all registered Overture Maps types organized by theme,
    including model class names and docstrings.

    \b
    Examples:
      # List all types
      $ overture-schema list-types
    """
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
