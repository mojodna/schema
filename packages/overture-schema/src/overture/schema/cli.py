"""Click-based CLI for overture-schema package."""

import inspect
import json
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from pydantic import BaseModel, ValidationError
from rich.console import Console
from rich.text import Text
from yamlcore import CoreLoader  # type: ignore

from overture.schema import create_union_from_models, parse_feature
from overture.schema.core.discovery import ModelKey, discover_models
from overture.schema.core.json_schema import json_schema

# Create a console instances for rich output
stdout = Console()
stderr = Console(file=sys.stderr)


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


def filter_tagged_union_from_path(loc: tuple[str | int, ...]) -> list[str | int]:
    """Filter out tagged-union noise from validation error path.

    Args:
        loc: Tuple of path components from Pydantic validation error

    Returns:
        List of path components with tagged-union elements removed
    """
    filtered_loc: list[str | int] = []
    for part in loc:
        # Skip tagged-union[...] elements
        if isinstance(part, str) and part.startswith("tagged-union["):
            continue
        else:
            filtered_loc.append(part)
    return filtered_loc


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


def format_validation_error(error: Any, console: Console) -> None:  # noqa: ANN401
    """Format and print a single validation error.

    Args:
        error: Pydantic validation error dict
        console: Rich Console instance for output
    """
    loc = error["loc"]

    # Filter out tagged-union noise from the path
    filtered_loc = filter_tagged_union_from_path(loc)

    # Convert to dot-separated path
    path_str = format_path(filtered_loc)

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

        # Convert from GeoJSON to flat format if necessary
        if data["type"] == "Feature":
            data = flatten_geojson(data)

        # Validate using parse_feature
        parse_feature(data, model_type)

        stdout.print(f"✓ Successfully validated {source_name}")

    except yaml.YAMLError as e:
        stderr.print(f"Error: '{source_name}' contains invalid input: {e}")
        sys.exit(1)

    except ValidationError as e:
        stderr.print("Validation failed:", style="red")
        stderr.print()

        for error in e.errors():
            format_validation_error(error, stderr)

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
