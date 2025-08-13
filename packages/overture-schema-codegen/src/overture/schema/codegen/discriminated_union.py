"""Discriminated union handling for Spark code generation."""

from typing import Any

from pydantic import BaseModel

from .case_class_generation import generate_simple_case_class
from .field_processing import (
    generate_column_aliases_for_flattened,
    generate_schema_fields_from_list,
)
from .filter_methods import generate_simple_filter_methods_with_casting
from .introspection import FieldInfo, extract_fields_recursive
from .scala_utils import (
    escape_scala_keyword,
    generate_trait_name,
    get_discriminator_value,
)
from .type_mapping import map_python_type_to_spark_type


def generate_spark_discriminated_union(
    union_type: Any,
    discriminator: str,
    variants: list[type[BaseModel]],
    package: str | None = None,
) -> str:
    """Generate Spark-compatible flattened case class for discriminated union."""

    # Generate flattened case class name from variants
    flattened_name = generate_trait_name([v.__name__ for v in variants])

    package_line = f"package {package}\n\n" if package else ""

    imports = [
        "import org.apache.spark.sql.types._",
        "import org.apache.spark.sql.{Dataset, SparkSession}",
        "import org.apache.spark.sql.functions.col",
    ]

    imports_section = "\n".join(imports) + "\n\n"

    # Collect all nested models from all variants (for generating nested case classes)
    all_nested_models = set()

    # Collect all fields from all variants
    all_fields = {}
    all_schema_fields = []

    # Add discriminator field first
    all_fields[discriminator] = {
        "scala_type": "String",
        "is_nullable": False,
        "default_value": None,
        "alias": None,
        "spark_type": "StringType",
    }
    all_schema_fields.append(
        {"name": discriminator, "type": "StringType", "nullable": False}
    )

    # Collect fields from all variants
    for variant in variants:
        fields = extract_fields_recursive(variant)
        for field in fields:
            if field.name.startswith("<") or "." in field.name:
                continue  # Skip special fields and nested fields

            if field.name == discriminator:
                continue  # Already handled discriminator

            # Collect nested models for case class generation
            if field.nested_model and field.nested_model not in all_nested_models:
                all_nested_models.add(field.nested_model)

            field_name = field.name

            # Check if this field already exists from another variant
            if field_name not in all_fields:
                # Import the mapping function from type_mapping module
                from .type_mapping import map_python_type_to_spark_scala

                # New field - make it optional since it won't exist in all variants
                scala_type = map_python_type_to_spark_scala(
                    field.annotation,
                    True,
                    field.name,  # Force nullable for variant-specific fields
                )

                all_fields[field_name] = {
                    "scala_type": scala_type,
                    "is_nullable": True,  # Always nullable in flattened approach
                    "default_value": None,  # Default to None for variant-specific fields
                    "alias": field.alias,
                    "spark_type": map_python_type_to_spark_type(
                        field.annotation, field.name
                    ),
                }

                # Add to schema fields
                schema_field_name = field.alias if field.alias else field.name
                all_schema_fields.append(
                    {
                        "name": schema_field_name,
                        "type": map_python_type_to_spark_type(
                            field.annotation, schema_field_name
                        ),
                        "nullable": True,  # Always nullable in flattened approach
                    }
                )

    # Generate flattened case class fields
    scala_fields = []
    for field_name, field_info in all_fields.items():
        escaped_name = escape_scala_keyword(field_name)
        scala_type = field_info["scala_type"]

        if field_name == discriminator:
            # Discriminator field is required
            scala_fields.append(f"  {escaped_name}: {scala_type}")
        else:
            # All variant-specific fields are optional with None default
            scala_fields.append(f"  {escaped_name}: {scala_type} = None")

    fields_str = ",\n".join(scala_fields)

    # Generate schema fields
    schema_fields_str = generate_schema_fields_from_list(all_schema_fields, "      ")

    # Generate column aliases for fields that have them
    alias_mappings = generate_column_aliases_for_flattened(all_fields)

    # Generate nested case classes first (recursively collect all dependencies)
    nested_case_classes = []
    processed_models = set()

    def collect_nested_recursively(model_set):
        """Recursively collect all nested models from a set of models."""
        new_models = set()
        for model in model_set:
            if model in processed_models:
                continue
            processed_models.add(model)

            # Get fields from this model and find more nested models
            fields = extract_fields_recursive(model)
            for field in fields:
                if field.nested_model and field.nested_model not in processed_models:
                    new_models.add(field.nested_model)

        if new_models:
            # Recursively process the new models found
            collect_nested_recursively(new_models)

        return new_models

    # Start with the initial nested models and recursively collect all dependencies
    collect_nested_recursively(all_nested_models)

    # Generate case classes for all collected models
    for nested_model in processed_models:
        nested_case_class = generate_simple_case_class(nested_model)
        nested_case_classes.append(nested_case_class)

    # Generate narrowed case classes for each variant
    narrowed_case_classes = generate_narrowed_case_classes(
        variants, discriminator, all_fields
    )

    # Generate filter methods for each variant (returning narrowed types using .as[])
    filter_methods = generate_simple_filter_methods_with_casting(
        flattened_name, discriminator, variants
    )

    # Generate narrowed case classes as a string to include before flattened case class
    narrowed_classes_str = (
        "\n\n".join(narrowed_case_classes) if narrowed_case_classes else ""
    )
    narrowed_classes = narrowed_classes_str + "\n\n" if narrowed_classes_str else ""

    # Generate the flattened case class
    flattened_case_class = f"""{narrowed_classes}/**
 * Flattened discriminated union with variants: {", ".join(v.__name__ for v in variants)}
 * Uses discriminator field '{discriminator}' to distinguish between variants.
 */
case class {flattened_name}(
{fields_str}
)

object {flattened_name} {{
  def fromDataFrame(df: org.apache.spark.sql.DataFrame)(implicit spark: SparkSession): Dataset[{flattened_name}] = {{
    import spark.implicits._
{alias_mappings}    df_aliased.as[{flattened_name}]
  }}

  def schema: StructType = {{
    StructType(Array(
{schema_fields_str}
    ))
  }}

{filter_methods}

{generate_conversion_methods(flattened_name, discriminator, variants, all_fields)}
}}"""

    # Combine everything with nested case classes first
    result = package_line + imports_section
    if nested_case_classes:
        result += "\n".join(nested_case_classes) + "\n\n"
    result += flattened_case_class

    return result


def generate_narrowed_case_classes(
    variants: list, discriminator: str, all_fields: dict
) -> list[str]:
    """Generate narrowed case classes for each variant."""
    narrowed_classes = []

    for variant in variants:
        # Generate simple narrowed case class with same fields as flattened
        variant_fields = extract_fields_recursive(variant)

        scala_fields = []
        for field in variant_fields:
            if field.name.startswith("<") or "." in field.name:
                continue
            if field.name == discriminator:
                continue

            field_name = escape_scala_keyword(field.name)
            if field.name in all_fields:
                field_info = all_fields[field.name]
                scala_type = field_info["scala_type"]
                scala_fields.append(f"  {field_name}: {scala_type}")

        fields_str = ",\n".join(scala_fields) if scala_fields else ""
        if fields_str:
            fields_str = f"\n{fields_str}\n"

        narrowed_class = f"""/**
 * Narrowed case class for {variant.__name__} variant.
 */
case class {variant.__name__}({fields_str})"""
        narrowed_classes.append(narrowed_class)

    return narrowed_classes


def generate_conversion_methods(
    flattened_name: str,
    discriminator: str,
    variants: list[type[BaseModel]],
    all_fields: dict,
) -> str:
    """Generate conversion methods from flattened to narrowed types."""
    methods = []

    for variant in variants:
        discriminator_value = get_discriminator_value(variant, discriminator)
        variant_fields = extract_fields_recursive(variant)

        # Build field assignments for conversion
        field_assignments = []
        for field in variant_fields:
            if field.name.startswith("<") or "." in field.name:
                continue
            if field.name == discriminator:
                continue

            field_name = escape_scala_keyword(field.name)
            if field.name in all_fields:
                field_assignments.append(f"        {field_name} = segment.{field_name}")

        assignments_str = ",\n".join(field_assignments) if field_assignments else ""
        if assignments_str:
            assignments_str = f"\n{assignments_str}\n      "

        method = f"""  def from{variant.__name__}(segment: {flattened_name}): Option[{variant.__name__}] = {{
    if (segment.{discriminator} == "{discriminator_value}") {{
    Some({variant.__name__}({assignments_str}))
    }} else None
  }}"""
        methods.append(method)

    return "\n\n".join(methods)
