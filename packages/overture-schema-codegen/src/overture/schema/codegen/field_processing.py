"""Field processing and alias handling utilities."""

from .introspection import FieldInfo
from .type_mapping import (
    generate_struct_type_for_model,
    is_direct_base_model,
    map_python_type_to_spark_type,
    map_python_type_to_spark_type_with_nested,
)


def generate_struct_fields(fields: list[FieldInfo], indent: str) -> str:
    """Generate StructField entries for Spark schema."""
    struct_fields = []
    processed_names = set()

    for field in fields:
        if (
            field.name.startswith("<")
            or "." in field.name
            or field.name in processed_names
        ):
            continue
        processed_names.add(field.name)

        # For schema, use the alias if available (column names should match the data)
        schema_field_name = field.alias if field.alias else field.name
        spark_type = map_python_type_to_spark_type(field.annotation, schema_field_name)
        nullable = str(field.is_nullable).lower()
        struct_fields.append(
            f'{indent}StructField("{schema_field_name}", {spark_type}, {nullable})'
        )

    return ",\n".join(struct_fields)


def generate_struct_fields_with_nested(fields: list[FieldInfo], indent: str) -> str:
    """Generate StructField entries for Spark schema, handling nested structures."""
    struct_fields = []
    processed_names = set()

    for field in fields:
        if (
            field.name.startswith("<")
            or "." in field.name
            or field.name in processed_names
        ):
            continue
        processed_names.add(field.name)

        # For schema, use the alias if available (column names should match the data)
        schema_field_name = field.alias if field.alias else field.name

        # Handle nested structures - only use nested_model if it's a direct BaseModel field
        if field.nested_model and is_direct_base_model(field.annotation):
            spark_type = generate_struct_type_for_model(field.nested_model)
        else:
            spark_type = map_python_type_to_spark_type_with_nested(
                field.annotation, schema_field_name
            )

        nullable = str(field.is_nullable).lower()
        struct_fields.append(
            f'{indent}StructField("{schema_field_name}", {spark_type}, {nullable})'
        )

    return ",\n".join(struct_fields)


def generate_schema_fields_from_list(schema_fields: list[dict], indent: str) -> str:
    """Generate StructField entries from schema field list."""
    struct_fields = []
    for field in schema_fields:
        # Use original field names for schema (column names should match the data)
        nullable = str(field["nullable"]).lower()
        struct_fields.append(
            f'{indent}StructField("{field["name"]}", {field["type"]}, {nullable})'
        )
    return ",\n".join(struct_fields)


def generate_column_aliases(fields: list[FieldInfo]) -> str:
    """Generate column alias mappings for fields that have aliases."""
    alias_lines = []
    has_aliases = False

    for field in fields:
        if (
            field.name.startswith("<")
            or "." in field.name
            or not field.alias
            or field.alias == field.name
        ):
            continue

        # Use the escaped field name for the alias target
        alias_lines.append(f'      col("{field.alias}").alias("{field.name}")')
        has_aliases = True

    if not has_aliases:
        return "    val df_aliased = df\n"

    # Generate the select statement with aliases
    alias_select = ",\n".join(alias_lines)
    # For drop, use the original alias names
    drops = [
        f'"{field.alias}"'
        for field in fields
        if field.alias
        and field.alias != field.name
        and not field.name.startswith("<")
        and "." not in field.name
    ]
    drop_clause = f".drop({', '.join(drops)})" if drops else ""
    return f"""    val df_aliased = df.select(
      col("*"),  // Select all existing columns
{alias_select}
    ){drop_clause}  // Drop original aliased columns to avoid duplicates
"""


def generate_column_aliases_for_flattened(all_fields: dict) -> str:
    """Generate column alias mappings for flattened case class fields that have aliases."""
    alias_lines = []
    has_aliases = False

    for field_name, field_info in all_fields.items():
        alias = field_info.get("alias")
        if alias and alias != field_name:
            alias_lines.append(f'      col("{alias}").alias("{field_name}")')
            has_aliases = True

    if not has_aliases:
        return "    val df_aliased = df\n"

    # Generate the select statement with aliases
    alias_select = ",\n".join(alias_lines)
    # For drop, use the original alias names
    drops = [
        f'"{field_info["alias"]}"'
        for field_name, field_info in all_fields.items()
        if field_info.get("alias") and field_info["alias"] != field_name
    ]
    drop_clause = f".drop({', '.join(drops)})" if drops else ""
    return f"""    val df_aliased = df.select(
      col("*"),  // Select all existing columns
{alias_select}
    ){drop_clause}  // Drop original aliased columns to avoid duplicates
"""
