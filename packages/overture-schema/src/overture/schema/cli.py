"""Click-based CLI for overture-schema package."""

import inspect
import json
import sys
from typing import Any

import click
from pydantic import BaseModel
from rich.console import Console
from rich.text import Text

from overture.schema import create_union_from_models
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
    type_names: tuple[str, ...], theme_names: tuple[str, ...], use_overture_types: bool
) -> Any:  # noqa: ANN401
    """Resolve CLI options into a model type suitable for parse_feature.

    Args:
        type_names: List of type names from --type option
        theme_names: List of theme names from --theme option
        use_overture_types: Boolean from --overture-types flag

    Returns:
        Model type suitable for passing to parse_feature
    """
    # Discover all available models via entry points
    all_models = discover_models()

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


@cli.command()
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
@click.option(
    "--overture-types",
    is_flag=True,
    help="Validate against all official Overture types (excludes extensions)",
)
def validate(
    type: tuple[str, ...], theme: tuple[str, ...], overture_types: bool
) -> None:
    """Validate Overture Maps data against schemas."""
    # TODO: Implement validation functionality
    try:
        model_type = resolve_types(type, theme, overture_types)
        stdout.print("Validate command - not yet implemented")
        stdout.print(f"Model type resolved: {repr(model_type)}")
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)


@cli.command("json-schema")
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
@click.option(
    "--overture-types",
    is_flag=True,
    help="Generate schema for all official Overture types (excludes extensions)",
)
def json_schema_command(
    type: tuple[str, ...], theme: tuple[str, ...], overture_types: bool
) -> None:
    """Generate JSON schema for Overture Maps types."""
    try:
        model_type = resolve_types(type, theme, overture_types)
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
