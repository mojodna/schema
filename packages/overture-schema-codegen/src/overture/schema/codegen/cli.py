"""Click-based CLI for overture-schema-codegen package."""

import importlib
import inspect
from typing import Any

import click
from pydantic import BaseModel

from .introspection import (
    extract_fields_recursive,
    get_model_hierarchy,
    is_discriminated_union,
)
from .plantuml import (
    generate_combined_plantuml_diagram,
    generate_plantuml_class_diagram,
)
from .spark_scala import generate_spark_scala_code


@click.group()
@click.version_option(package_name="overture-schema-codegen")
def cli() -> None:
    """Overture Schema Code Generation command-line interface."""
    pass


def _load_model_class(module_path: str, class_name: str) -> type[BaseModel] | Any:
    """Load a Pydantic model class or discriminated union from a module path."""
    try:
        module = importlib.import_module(module_path)
        model_class_or_union = getattr(module, class_name)

        # Check if it's a regular BaseModel class
        if inspect.isclass(model_class_or_union) and issubclass(
            model_class_or_union, BaseModel
        ):
            return model_class_or_union

        # Check if it's a discriminated union
        is_union, discriminator, variants = is_discriminated_union(model_class_or_union)
        if is_union:
            return model_class_or_union

        # If neither, it's an error
        raise ValueError(
            f"{class_name} is neither a Pydantic BaseModel nor a discriminated union"
        )

    except ImportError as e:
        raise click.ClickException(f"Failed to import module '{module_path}': {e}")
    except AttributeError:
        raise click.ClickException(
            f"Class '{class_name}' not found in module '{module_path}'"
        )
    except ValueError as e:
        raise click.ClickException(str(e))


def _discover_overture_models() -> list[type[BaseModel] | Any]:
    """Discover all Overture schema models from the workspace."""
    try:
        from overture.schema.core.discovery import discover_models

        models = discover_models()
        return list(models.values())
    except ImportError:
        click.echo("Warning: Could not import overture.schema.core.discovery", err=True)
        return []


@cli.command()
@click.option(
    "--format",
    type=click.Choice(
        [
            "spark-scala",
            "scala",
            "typescript",
            "rust",
            "introspect",
        ],
        case_sensitive=False,
    ),
    default="introspect",
    help="Target language/format for code generation (default: introspect for debugging)",
)
@click.option(
    "--model",
    help="Specific model to generate code for (format: module.path:ClassName)",
)
@click.option(
    "--discover",
    is_flag=True,
    help="Auto-discover all Overture schema models",
)
@click.option(
    "--package",
    help="Package name for generated code (e.g., com.overture.spark)",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    help="Output directory for generated files",
)
@click.option(
    "--hierarchy",
    is_flag=True,
    help="Show hierarchical model structure (introspect format only)",
)
@click.option(
    "--with-validation",
    is_flag=True,
    help="Generate validation code alongside main code (spark-scala format only)",
)
def generate(
    format: str,
    model: str | None,
    discover: bool,
    package: str | None,
    output_dir: str | None,
    hierarchy: bool,
    with_validation: bool,
) -> None:
    """Generate code from Overture Maps schema models."""

    models_to_process: list[type[BaseModel] | Any] = []

    # Determine which models to process
    if model:
        if ":" not in model:
            raise click.ClickException(
                "Model must be in format 'module.path:ClassName'"
            )

        module_path, class_name = model.split(":", 1)
        model_class = _load_model_class(module_path, class_name)
        models_to_process.append(model_class)

    elif discover:
        models_to_process = _discover_overture_models()
        if not models_to_process:
            raise click.ClickException(
                "No models discovered. Make sure overture-schema packages are installed."
            )

    else:
        raise click.ClickException("Must specify either --model or --discover")

    click.echo(
        f"Processing {len(models_to_process)} model(s) with format: {format}", err=True
    )

    # Process each model
    for model_class in models_to_process:
        if format == "introspect":
            # Handle naming for discriminated unions
            is_union, discriminator, variants = is_discriminated_union(model_class)
            if is_union and variants and discriminator:
                name = f"DiscriminatedUnion[{', '.join(v.__name__ for v in variants)}]"
                click.echo(f"\n=== {name} ===")
                click.echo(f"  Discriminator field: {discriminator}")
                click.echo(f"  Variants: {[v.__name__ for v in variants]}")
            else:
                click.echo(f"\n=== {model_class.__name__} ===")

            if hierarchy and not is_union:
                # Show hierarchical structure (only for regular models)
                hierarchy_data = get_model_hierarchy(model_class)
                _print_hierarchy(hierarchy_data)
            else:
                # Show flat field list
                try:
                    fields = extract_fields_recursive(model_class)
                    for field in fields:
                        if field.is_discriminated_union:
                            click.echo(f"  {field.name}: Discriminated Union")
                            click.echo(
                                f"    Discriminator: {field.discriminator_field}"
                            )
                            if field.union_variants:
                                click.echo(
                                    f"    Variants: {[v.__name__ for v in field.union_variants]}"
                                )
                        else:
                            type_name = getattr(
                                field.python_type, "__name__", str(field.python_type)
                            )
                            click.echo(f"  {field.name}: {type_name}")
                            if field.description:
                                click.echo(f"    Description: {field.description}")
                            if field.nested_model:
                                click.echo(
                                    f"    Nested Model: {field.nested_model.__name__}"
                                )
                except Exception as e:
                    click.echo(f"  Error processing: {e}", err=True)
        elif format == "spark-scala":
            try:
                # Generate main Scala code
                scala_code = generate_spark_scala_code(
                    model_class, package, with_validation
                )

                # Get model name for file naming
                is_union, discriminator, variants = is_discriminated_union(model_class)
                if is_union and variants:
                    model_name = f"Union_{len(variants)}_variants"
                else:
                    model_name = model_class.__name__

                # Validation is now integrated into the main Scala code generation

                # Output handling
                if output_dir:
                    import os

                    os.makedirs(output_dir, exist_ok=True)

                    # Write main Scala code
                    filename = f"{model_name}.scala"
                    filepath = os.path.join(output_dir, filename)
                    with open(filepath, "w") as f:
                        f.write(scala_code)
                    click.echo(f"  Generated Scala code written to: {filepath}")

                    # Validation is now integrated into the main Scala file
                else:
                    # Output to stdout
                    click.echo("=== Main Scala Code ===")
                    click.echo(scala_code)

                    # Validation is now integrated into the main Scala code

            except Exception as e:
                click.echo(f"  Error generating Spark Scala code: {e}", err=True)

        else:
            click.echo(f"  Format '{format}' - not yet implemented")


@cli.command()
@click.option(
    "--model",
    help="Specific model to generate diagram for (format: module.path:ClassName)",
)
@click.option(
    "--discover",
    is_flag=True,
    help="Auto-discover all Overture schema models",
)
@click.option(
    "--include-nested",
    is_flag=True,
    default=True,
    help="Include nested models in diagram (default: True)",
)
@click.option(
    "--show-types",
    is_flag=True,
    default=True,
    help="Show field types in diagram (default: True)",
)
@click.option(
    "--show-descriptions",
    is_flag=True,
    help="Show field descriptions as notes",
)
@click.option(
    "--output",
    type=click.Path(),
    help="Output file for diagram (default: stdout)",
)
def diagram(
    model: str | None,
    discover: bool,
    include_nested: bool,
    show_types: bool,
    show_descriptions: bool,
    output: str | None,
) -> None:
    """Generate PlantUML class diagrams from Pydantic models."""

    models_to_process: list[type[BaseModel] | Any] = []

    # Determine which models to process (same logic as generate command)
    if model:
        if ":" not in model:
            raise click.ClickException(
                "Model must be in format 'module.path:ClassName'"
            )

        module_path, class_name = model.split(":", 1)
        model_class = _load_model_class(module_path, class_name)
        models_to_process.append(model_class)

    elif discover:
        models_to_process = _discover_overture_models()
        if not models_to_process:
            raise click.ClickException(
                "No models discovered. Make sure overture-schema packages are installed."
            )

    else:
        raise click.ClickException("Must specify either --model or --discover")

    # Generate PlantUML diagram
    try:
        if len(models_to_process) > 1:
            # Use combined diagram generation for multiple models to avoid duplicates
            click.echo(
                f"Generating combined diagram for {len(models_to_process)} models",
                err=True,
            )
            final_output = generate_combined_plantuml_diagram(
                models_to_process,
                include_nested=include_nested,
                show_field_types=show_types,
                show_descriptions=show_descriptions,
            )
        else:
            # Single model - use individual diagram generation
            model_class = models_to_process[0]
            is_union, discriminator, variants = is_discriminated_union(model_class)
            if is_union and variants:
                name = f"DiscriminatedUnion[{', '.join(v.__name__ for v in variants)}]"
                click.echo(f"Generating diagram for {name}", err=True)
            else:
                click.echo(f"Generating diagram for {model_class.__name__}", err=True)

            final_output = generate_plantuml_class_diagram(
                model_class,
                include_nested=include_nested,
                show_field_types=show_types,
                show_descriptions=show_descriptions,
            )
    except Exception as e:
        click.echo(f"Error generating diagram: {e}", err=True)
        final_output = ""

    # Output the result
    if output:
        with open(output, "w") as f:
            f.write(final_output)
        click.echo(f"Diagram written to {output}", err=True)
    else:
        click.echo(final_output)


def _print_hierarchy(hierarchy: dict[str, Any], indent: int = 0) -> None:
    """Print hierarchical model structure."""
    prefix = "  " * indent
    click.echo(f"{prefix}Model: {hierarchy['name']}")

    if hierarchy["fields"]:
        click.echo(f"{prefix}Fields:")
        for field_name, field_info in hierarchy["fields"].items():
            required = "required" if field_info["required"] else "optional"
            nullable = "nullable" if field_info["nullable"] else "non-null"
            click.echo(
                f"{prefix}  - {field_name}: {field_info['type']} ({required}, {nullable})"
            )
            if field_info.get("description"):
                click.echo(f"{prefix}    Description: {field_info['description']}")

    if hierarchy["nested_models"]:
        click.echo(f"{prefix}Nested Models:")
        for nested_hierarchy in hierarchy["nested_models"].values():
            _print_hierarchy(nested_hierarchy, indent + 1)


if __name__ == "__main__":
    cli()
