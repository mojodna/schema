"""Click-based CLI for overture-schema package."""

import json
import sys
from pathlib import Path
from typing import Any

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
from .type_analysis import introspect_union

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


@click.group()
@click.version_option(package_name="overture-schema")
def cli() -> None:
    """Overture Schema command-line interface."""
    pass


def load_input(filename: Path | None) -> tuple[Any, str]:
    """Load and parse input from file or stdin.

    Args:
        filename: Path to input file, None for stdin, or "-" for explicit stdin

    Returns:
        Tuple of (parsed_data, source_name)

    Raises:
        yaml.YAMLError: If input is invalid YAML/JSON
        SystemExit: If filename doesn't exist or isn't a file
    """
    use_stdin = filename is None or str(filename) == "-"
    source_name = "<stdin>" if use_stdin else str(filename)

    if not use_stdin and not filename.is_file():
        stderr.print(f"Error: '{filename}' is not a file.")
        sys.exit(1)

    # Use YAML-1.2-compliant loader (YAML-1.2 dropped support for yes/no boolean values)
    if use_stdin:
        data = yaml.load(sys.stdin, Loader=CoreLoader)
    else:
        with filename.open("r", encoding="utf-8") as f:
            data = yaml.load(f, Loader=CoreLoader)

    return data, source_name


def perform_validation(data: Any, model_type: Any) -> None:  # noqa: ANN401
    """Validate data based on its structure.

    Handles single features, lists of features, and GeoJSON FeatureCollections.

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
    try:
        model_type = resolve_types(overture_types, namespace, theme, type)
        data, source_name = load_input(filename)
        perform_validation(data, model_type)

        stdout.print(f"✓ Successfully validated {source_name}")

    except yaml.YAMLError as e:
        # Get source name for error message
        source_name = (
            "<stdin>" if (filename is None or str(filename) == "-") else str(filename)
        )
        stderr.print(f"Error: '{source_name}' contains invalid input: {e}")
        sys.exit(1)

    except ValidationError as e:
        stderr.print("Validation failed:", style="red")
        stderr.print()

        # Compute metadata once upfront
        metadata = introspect_union(model_type)

        # Group errors by discriminator path and select most likely group(s)
        error_groups = group_errors_by_discriminator(e.errors(), metadata)
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
            format_validation_error(
                error, stderr, metadata=metadata, show_model_hint=(i == 0)
            )

        sys.exit(1)

    except ValueError as e:
        # User error (e.g., no models found matching criteria)
        stderr.print(f"Error: {e}")
        sys.exit(1)

    except KeyError as e:
        # Data structure error (e.g., missing "features" in FeatureCollection)
        stderr.print(f"Error: Invalid data structure - missing key: {e}")
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
        sys.exit(1)


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
