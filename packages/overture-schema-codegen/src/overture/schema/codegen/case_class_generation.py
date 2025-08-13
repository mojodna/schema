"""Case class generation utilities for Pydantic models."""

import inspect

from pydantic import BaseModel

from .field_processing import (
    generate_column_aliases,
    generate_struct_fields_with_nested,
)
from .introspection import FieldInfo, extract_fields_recursive
from .scala_utils import escape_scala_keyword, format_scala_default_value
from .type_mapping import (
    is_nullable_annotation,
    map_python_type_to_spark_scala_with_nested,
)


def generate_spark_case_class_with_nested(
    model_class: type[BaseModel], package: str | None = None
) -> str:
    """Generate Spark-compatible case class from Pydantic model with nested structures."""

    # Extract all fields including nested ones
    fields = extract_fields_recursive(model_class)

    # Collect all nested models that need case classes
    nested_models = set()
    for field in fields:
        if field.nested_model and field.nested_model not in nested_models:
            nested_models.add(field.nested_model)

    # Generate package declaration
    package_line = f"package {package}\n\n" if package else ""

    # Standard Spark imports
    imports = [
        "import org.apache.spark.sql.types._",
        "import org.apache.spark.sql.{Dataset, SparkSession}",
        "import org.apache.spark.sql.functions.col",
    ]
    imports_section = "\n".join(imports) + "\n\n" if imports else ""

    # Generate nested case classes first
    nested_case_classes = []
    for nested_model in nested_models:
        nested_case_class = generate_simple_case_class(nested_model)
        nested_case_classes.append(nested_case_class)

    # Generate main case class
    main_case_class = generate_main_case_class(model_class, fields)

    # Combine everything
    result = package_line + imports_section
    if nested_case_classes:
        result += "\n".join(nested_case_classes) + "\n\n"
    result += main_case_class

    return result


def generate_simple_case_class(model_class: type[BaseModel]) -> str:
    """Generate a simple case class for a nested model without companion object."""
    class_name = model_class.__name__
    docstring = (
        inspect.getdoc(model_class) or f"Generated from Pydantic model {class_name}"
    )

    # Get only the direct fields of this model (not recursive)
    direct_fields = []
    for field_name, field_info in model_class.model_fields.items():
        field_data = FieldInfo(
            name=field_name,
            python_type=field_info.annotation,
            annotation=field_info.annotation,
            is_required=field_info.is_required(),
            is_nullable=is_nullable_annotation(field_info.annotation),
            default_value=field_info.default
            if hasattr(field_info, "default")
            else None,
            description=field_info.description,
            alias=getattr(field_info, "alias", None),
        )
        direct_fields.append(field_data)

    # Generate fields for case class
    scala_fields = []
    for field in direct_fields:
        field_name = escape_scala_keyword(field.name)
        scala_type = map_python_type_to_spark_scala_with_nested(
            field.annotation, field.is_nullable, field.name
        )

        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = format_scala_default_value(field.default_value, scala_type)
            if default_str is not None:  # Only add default if it's type-compatible
                scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
            else:
                scala_fields.append(f"  {field_name}: {scala_type}")
        else:
            scala_fields.append(f"  {field_name}: {scala_type}")

    fields_str = ",\n".join(scala_fields)

    return f"""/**
 * {docstring}
 */
case class {class_name}(
{fields_str}
)"""


def generate_main_case_class(
    model_class: type[BaseModel], fields: list[FieldInfo]
) -> str:
    """Generate the main case class with companion object."""
    class_name = model_class.__name__
    docstring = (
        inspect.getdoc(model_class) or f"Generated from Pydantic model {class_name}"
    )

    # Generate fields using top-level fields only (not nested)
    scala_fields = []
    for field in fields:
        if field.name.startswith("<") or "." in field.name:
            continue  # Skip special fields and nested fields for case class

        field_name = escape_scala_keyword(field.name)
        scala_type = map_python_type_to_spark_scala_with_nested(
            field.annotation, field.is_nullable, field.name
        )

        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = format_scala_default_value(field.default_value, scala_type)
            if default_str is not None:  # Only add default if it's type-compatible
                scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
            else:
                scala_fields.append(f"  {field_name}: {scala_type}")
        else:
            scala_fields.append(f"  {field_name}: {scala_type}")

    # Generate case class
    fields_str = ",\n".join(scala_fields)
    struct_fields_str = generate_struct_fields_with_nested(fields, "      ")

    # Generate column aliases for fields that have them
    alias_mappings = generate_column_aliases(fields)

    return f"""/**
 * {docstring}
 */
case class {class_name}(
{fields_str}
)

object {class_name} {{
  def fromDataFrame(df: org.apache.spark.sql.DataFrame)(implicit spark: SparkSession): Dataset[{class_name}] = {{
    import spark.implicits._
{alias_mappings}    df_aliased.as[{class_name}]
  }}

  def schema: StructType = {{
    StructType(Array(
{struct_fields_str}
    ))
  }}
}}"""
