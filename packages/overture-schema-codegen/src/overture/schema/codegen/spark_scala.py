"""Spark-compatible Scala code generator from Pydantic models."""

import inspect
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import BaseModel

from .introspection import FieldInfo, extract_fields_recursive, is_discriminated_union

try:
    from overture.schema.core.types.abstract import get_abstract_type, get_target_type
except ImportError:
    # Fallback if abstract types are not available
    def get_abstract_type(python_type):
        return None

    def get_target_type(abstract_type, target):
        return None


def generate_spark_scala_code(
    model_class: type[BaseModel] | Any, package: str | None = None
) -> str:
    """Generate Spark-compatible Scala code from Pydantic model or discriminated union."""

    # Check if it's a discriminated union
    is_union, discriminator, variants = is_discriminated_union(model_class)

    if is_union and variants:
        return _generate_spark_discriminated_union(
            model_class, discriminator, variants, package
        )
    elif inspect.isclass(model_class) and issubclass(model_class, BaseModel):
        return _generate_spark_case_class_with_nested(model_class, package)
    else:
        raise ValueError(f"Cannot generate Spark Scala code for: {model_class}")


def _generate_spark_case_class(
    model_class: type[BaseModel], package: str | None = None
) -> str:
    """Generate Spark-compatible case class from Pydantic model."""

    class_name = model_class.__name__
    docstring = (
        inspect.getdoc(model_class) or f"Generated from Pydantic model {class_name}"
    )

    # Generate package declaration
    package_line = f"package {package}\n\n" if package else ""

    # Standard Spark imports
    imports = [
        "import org.apache.spark.sql.types._",
        "import org.apache.spark.sql.{Dataset, SparkSession}",
        "import org.apache.spark.sql.functions.col",
    ]

    imports_section = "\n".join(imports) + "\n\n" if imports else ""

    # Generate fields using FieldInfo
    fields = extract_fields_recursive(model_class)
    scala_fields = []

    for field in fields:
        if field.name.startswith("<") or "." in field.name:
            continue  # Skip special fields and nested fields for case class

        # Use original field name for Scala case class, escape if needed
        field_name = _escape_scala_keyword(field.name)

        scala_type = _map_python_type_to_spark_scala(
            field.python_type, field.is_nullable, field.name
        )

        # Handle default values - skip PydanticUndefined
        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = _format_scala_default_value(field.default_value, scala_type)
            scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
        else:
            scala_fields.append(f"  {field_name}: {scala_type}")

    # Generate case class
    fields_str = ",\n".join(scala_fields)
    struct_fields_str = _generate_struct_fields(fields, "      ")

    # Generate column aliases for fields that have them
    alias_mappings = _generate_column_aliases(fields)

    case_class = f"""/**
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

    return package_line + imports_section + case_class


def _generate_spark_case_class_with_nested(
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
        nested_case_class = _generate_simple_case_class(nested_model)
        nested_case_classes.append(nested_case_class)

    # Generate main case class
    main_case_class = _generate_main_case_class(model_class, fields)

    # Combine everything
    result = package_line + imports_section
    if nested_case_classes:
        result += "\n".join(nested_case_classes) + "\n\n"
    result += main_case_class

    return result


def _generate_simple_case_class(model_class: type[BaseModel]) -> str:
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
            is_nullable=_is_nullable_annotation(field_info.annotation),
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
        field_name = _escape_scala_keyword(field.name)
        scala_type = _map_python_type_to_spark_scala_with_nested(
            field.python_type, field.is_nullable, field.name
        )

        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = _format_scala_default_value(field.default_value, scala_type)
            scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
        else:
            scala_fields.append(f"  {field_name}: {scala_type}")

    fields_str = ",\n".join(scala_fields)

    return f"""/**
 * {docstring}
 */
case class {class_name}(
{fields_str}
)"""


def _generate_main_case_class(
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

        field_name = _escape_scala_keyword(field.name)
        scala_type = _map_python_type_to_spark_scala_with_nested(
            field.python_type, field.is_nullable, field.name
        )

        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = _format_scala_default_value(field.default_value, scala_type)
            scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
        else:
            scala_fields.append(f"  {field_name}: {scala_type}")

    # Generate case class
    fields_str = ",\n".join(scala_fields)
    struct_fields_str = _generate_struct_fields_with_nested(fields, "      ")

    # Generate column aliases for fields that have them
    alias_mappings = _generate_column_aliases(fields)

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


def _map_python_type_to_spark_scala_with_nested(
    python_type: type, is_nullable: bool = False, field_name: str = ""
) -> str:
    """Map Python types to Spark-compatible Scala types, handling nested models."""
    # Special case for geometry field - always Array[Byte] for binary data
    if field_name == "geometry":
        return "Array[Byte]" if not is_nullable else "Option[Array[Byte]]"

    # Check if this is a BaseModel (nested structure)
    if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        scala_type = python_type.__name__
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type

    # Handle NewType by checking the underlying type
    if hasattr(python_type, "__supertype__"):
        underlying_type = python_type.__supertype__
        return _map_python_type_to_spark_scala_with_nested(
            underlying_type, is_nullable, field_name
        )

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return _map_python_type_to_spark_scala_with_nested(
                actual_type, is_nullable, field_name
            )

    # Handle Optional types (both Union[T, None] and T | None syntax)
    import types

    # Handle new union syntax (Python 3.10+) and traditional Union
    if origin is Union or isinstance(python_type, types.UnionType):
        if isinstance(python_type, types.UnionType):
            args = python_type.__args__
        else:
            args = get_args(python_type)

        # Check for Optional pattern (Union[T, None] or T | None)
        if len(args) == 2 and type(None) in args:
            non_none_type = args[0] if args[1] is type(None) else args[1]
            # Recursively handle the non-None type
            return _map_python_type_to_spark_scala_with_nested(
                non_none_type, True, field_name
            )

    # Handle collections before falling back
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_scala = _map_python_type_to_spark_scala_with_nested(inner_type, False, "")
        scala_type = f"Array[{inner_scala}]"
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type
    elif origin is dict:
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = _map_python_type_to_spark_scala_with_nested(args[0], False, "")
            value_type = _map_python_type_to_spark_scala_with_nested(args[1], False, "")
            scala_type = f"Map[{key_type}, {value_type}]"
        else:
            scala_type = "Map[String, String]"  # Default fallback
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type

    # Fall back to original mapping
    return _map_python_type_to_spark_scala(python_type, is_nullable, field_name)


def _generate_struct_fields_with_nested(fields: list[FieldInfo], indent: str) -> str:
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

        # Handle nested structures
        if field.nested_model:
            spark_type = _generate_struct_type_for_model(field.nested_model)
        else:
            spark_type = _map_python_type_to_spark_type_with_nested(
                field.python_type, schema_field_name
            )

        nullable = str(field.is_nullable).lower()
        struct_fields.append(
            f'{indent}StructField("{schema_field_name}", {spark_type}, {nullable})'
        )

    return ",\n".join(struct_fields)


def _generate_struct_type_for_model(model_class: type[BaseModel]) -> str:
    """Generate a StructType definition for a nested Pydantic model."""
    struct_fields = []

    for field_name, field_info in model_class.model_fields.items():
        field_type = _map_python_type_to_spark_type_with_nested(
            field_info.annotation, field_name
        )
        nullable = str(_is_nullable_annotation(field_info.annotation)).lower()
        struct_fields.append(f'StructField("{field_name}", {field_type}, {nullable})')

    return f"StructType(Array({', '.join(struct_fields)}))"


def _map_python_type_to_spark_type_with_nested(
    python_type: type, field_name: str = ""
) -> str:
    """Map Python types to Spark SQL types using abstract type information, handling nested structures."""
    # Check if this is a BaseModel (nested structure)
    if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        return _generate_struct_type_for_model(python_type)

    # Handle NewType by checking the underlying type
    if hasattr(python_type, "__supertype__"):
        underlying_type = python_type.__supertype__
        return _map_python_type_to_spark_type_with_nested(underlying_type, field_name)

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return _map_python_type_to_spark_type_with_nested(actual_type, field_name)

    # Handle Optional types (both Union[T, None] and T | None syntax)
    import types

    # Handle new union syntax (Python 3.10+) and traditional Union
    if origin is Union or isinstance(python_type, types.UnionType):
        if isinstance(python_type, types.UnionType):
            args = python_type.__args__
        else:
            args = get_args(python_type)

        # Check for Optional pattern (Union[T, None] or T | None)
        if len(args) == 2 and type(None) in args:
            non_none_type = args[0] if args[1] is type(None) else args[1]
            # Recursively handle the non-None type
            return _map_python_type_to_spark_type_with_nested(non_none_type, field_name)

    # Handle collections
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_spark = _map_python_type_to_spark_type_with_nested(inner_type, "")
        return f"ArrayType({inner_spark})"
    elif origin is dict:
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = _map_python_type_to_spark_type_with_nested(args[0], "")
            value_type = _map_python_type_to_spark_type_with_nested(args[1], "")
            return f"MapType({key_type}, {value_type})"
        else:
            return "MapType(StringType, StringType)"  # Default fallback

    # Fall back to original mapping
    return _map_python_type_to_spark_type(python_type, field_name)


def _is_nullable_annotation(annotation: Any) -> bool:
    """Check if a type annotation represents a nullable field."""
    import types

    # Handle new union syntax (Python 3.10+)
    if isinstance(annotation, types.UnionType):
        return type(None) in annotation.__args__

    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        return type(None) in args

    return False


def _generate_spark_discriminated_union(
    union_type: Any,
    discriminator: str,
    variants: list[type[BaseModel]],
    package: str | None = None,
) -> str:
    """Generate Spark-compatible sealed trait for discriminated union."""

    # Generate trait name from variants
    trait_name = _generate_trait_name([v.__name__ for v in variants])

    package_line = f"package {package}\n\n" if package else ""

    imports = [
        "import org.apache.spark.sql.types._",
        "import org.apache.spark.sql.{Dataset, SparkSession, Column}",
        "import org.apache.spark.sql.functions._",
    ]

    imports_section = "\n".join(imports) + "\n\n"

    # Generate sealed trait
    sealed_trait = f"""/**
 * Discriminated union with variants: {", ".join(v.__name__ for v in variants)}
 */
sealed trait {trait_name} {{
  def {discriminator}: String
}}

"""

    # Generate case classes for each variant
    variant_classes = []
    all_schema_fields = []

    for variant in variants:
        fields = extract_fields_recursive(variant)
        scala_fields = []

        # Get discriminator value from the variant model
        discriminator_value = _get_discriminator_value(variant, discriminator)

        for field in fields:
            if field.name.startswith("<") or "." in field.name:
                continue  # Skip special fields and nested fields

            if field.name == discriminator:
                continue  # Skip discriminator field - handled in trait

            # Use original field name for Scala case class, escape if needed
            field_name = _escape_scala_keyword(field.name)

            scala_type = _map_python_type_to_spark_scala(
                field.python_type, field.is_nullable, field.name
            )

            if (
                field.default_value is not None
                and str(field.default_value) != "PydanticUndefined"
            ):
                default_str = _format_scala_default_value(
                    field.default_value, scala_type
                )
                scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
            else:
                scala_fields.append(f"  {field_name}: {scala_type}")

            # Add to schema fields if not already present
            schema_field_name = field.alias if field.alias else field.name
            spark_type = _map_python_type_to_spark_type(
                field.python_type, schema_field_name
            )
            schema_field = {
                "name": schema_field_name,
                "type": spark_type,
                "nullable": field.is_nullable,
            }
            if schema_field not in all_schema_fields:
                all_schema_fields.append(schema_field)

        # Add discriminator to schema (once)
        if discriminator not in [f["name"] for f in all_schema_fields]:
            all_schema_fields.append(
                {"name": discriminator, "type": "StringType", "nullable": False}
            )

        field_list = ",\n".join(scala_fields) if scala_fields else ""
        if field_list:
            field_list = f"\n{field_list}\n"

        variant_class = f"""case class {variant.__name__}({field_list}) extends {trait_name} {{
  override val {discriminator}: String = "{discriminator_value}"
}}

"""
        variant_classes.append(variant_class)

    # Generate companion object
    schema_fields_str = _generate_schema_fields_from_list(all_schema_fields, "      ")
    filter_methods_str = _generate_filter_methods(trait_name, discriminator, variants)

    companion = f"""object {trait_name} {{
  def fromDataFrame(df: org.apache.spark.sql.DataFrame)(implicit spark: SparkSession): Dataset[{trait_name}] = {{
    import spark.implicits._
    df.as[{trait_name}]
  }}

  def schema: StructType = {{
    StructType(Array(
{schema_fields_str}
    ))
  }}

{filter_methods_str}
}}"""

    return (
        package_line
        + imports_section
        + sealed_trait
        + "".join(variant_classes)
        + companion
    )


def _map_python_type_to_spark_scala(
    python_type: type, is_nullable: bool = False, field_name: str = ""
) -> str:
    """Map Python types to Spark-compatible Scala types using abstract type information."""
    # Special case for geometry field - always Array[Byte] for binary data
    if field_name == "geometry":
        return "Array[Byte]" if not is_nullable else "Option[Array[Byte]]"

    # Try to get target type directly (handles NewTypes and abstract types internally)
    scala_type = get_target_type(python_type, "scala")
    if scala_type:
        # Wrap with Option if nullable
        if is_nullable and not scala_type.startswith("Option["):
            scala_type = f"Option[{scala_type}]"
        return scala_type

    # Fallback to get_target_type for basic Python types
    scala_type = get_target_type(python_type, "scala")
    if not scala_type:
        scala_type = "String"  # Ultimate fallback

    # Handle collections
    origin = get_origin(python_type)
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_scala = _map_python_type_to_spark_scala(inner_type, False, "")
        scala_type = f"Array[{inner_scala}]"
    elif origin is dict:
        scala_type = "Map[String, String]"  # Simplification

    # Wrap with Option if nullable
    if is_nullable and not scala_type.startswith("Option["):
        scala_type = f"Option[{scala_type}]"

    return scala_type


def _map_python_type_to_spark_type(python_type: type, field_name: str = "") -> str:
    """Map Python types to Spark SQL types using abstract type information."""
    # Special case for geometry field - always BinaryType for binary data
    if field_name == "geometry":
        return "BinaryType"

    # Try to get target type directly (handles NewTypes and abstract types internally)
    spark_type = get_target_type(python_type, "spark")
    if spark_type:
        return spark_type

    # Handle collections before registry fallback
    origin = get_origin(python_type)
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_spark = _map_python_type_to_spark_type(inner_type, "")
        return f"ArrayType({inner_spark})"
    elif origin is dict:
        return "MapType(StringType, StringType)"

    # Fallback to get_target_type for basic Python types
    spark_type_result = get_target_type(python_type, "spark")
    return spark_type_result if spark_type_result else "StringType"  # Ultimate fallback


def _format_scala_default_value(default_value: Any, scala_type: str) -> str:
    """Format Python default values as Scala literals."""
    if isinstance(default_value, str):
        return (
            f'"{default_value}"'
            if not scala_type.startswith("Option[")
            else f'Some("{default_value}")'
        )
    elif isinstance(default_value, bool):
        bool_str = str(default_value).lower()
        return bool_str if not scala_type.startswith("Option[") else f"Some({bool_str})"
    elif isinstance(default_value, (int, float)):
        if isinstance(default_value, int):
            val_str = f"{default_value}L"
        else:
            val_str = str(default_value)
        return val_str if not scala_type.startswith("Option[") else f"Some({val_str})"
    elif isinstance(default_value, list):
        if not default_value:
            return (
                "Array.empty"
                if not scala_type.startswith("Option[")
                else "Some(Array.empty)"
            )
        items = ", ".join(
            f'"{item}"' if isinstance(item, str) else str(item)
            for item in default_value
        )
        array_str = f"Array({items})"
        return (
            array_str if not scala_type.startswith("Option[") else f"Some({array_str})"
        )
    else:
        return (
            f'"{default_value}"'
            if not scala_type.startswith("Option[")
            else f'Some("{default_value}")'
        )


def _generate_struct_fields(fields: list[FieldInfo], indent: str) -> str:
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
        spark_type = _map_python_type_to_spark_type(
            field.python_type, schema_field_name
        )
        nullable = str(field.is_nullable).lower()
        struct_fields.append(
            f'{indent}StructField("{schema_field_name}", {spark_type}, {nullable})'
        )

    return ",\n".join(struct_fields)


def _generate_schema_fields_from_list(schema_fields: list[dict], indent: str) -> str:
    """Generate StructField entries from schema field list."""
    struct_fields = []
    for field in schema_fields:
        # Use original field names for schema (column names should match the data)
        nullable = str(field["nullable"]).lower()
        struct_fields.append(
            f'{indent}StructField("{field["name"]}", {field["type"]}, {nullable})'
        )
    return ",\n".join(struct_fields)


def _generate_trait_name(variant_names: list[str]) -> str:
    """Generate trait name from variant class names."""
    # Find common suffix
    if not variant_names:
        return "UnknownUnion"

    # Simple heuristic: if all end with same suffix, use that
    shortest = min(variant_names, key=len)
    for i in range(len(shortest), 0, -1):
        suffix = shortest[-i:]
        if all(name.endswith(suffix) for name in variant_names) and len(suffix) > 2:
            return suffix

    # Fallback: concatenate prefixes
    prefixes = [
        name.replace("Segment", "").replace("Part", "") for name in variant_names
    ]
    return "".join(prefixes) + "Union"


def _get_discriminator_value(
    model_class: type[BaseModel], discriminator_field: str
) -> str:
    """Extract discriminator value from a Pydantic model."""
    if (
        hasattr(model_class, "model_fields")
        and discriminator_field in model_class.model_fields
    ):
        field_info = model_class.model_fields[discriminator_field]
        if (
            hasattr(field_info, "default")
            and field_info.default is not None
            and str(field_info.default) != "PydanticUndefined"
        ):
            return str(field_info.default)

    # Fallback: use class name transformation
    class_name = model_class.__name__.lower()
    if "road" in class_name:
        return "road"
    elif "rail" in class_name:
        return "rail"
    elif "water" in class_name:
        return "water"
    else:
        return class_name.replace("segment", "").replace("part", "")


def _escape_scala_keyword(field_name: str) -> str:
    """Escape Scala reserved keywords using backticks."""
    # Common Scala keywords that might conflict with field names
    scala_keywords = {
        "abstract",
        "case",
        "catch",
        "class",
        "def",
        "do",
        "else",
        "extends",
        "false",
        "final",
        "finally",
        "for",
        "if",
        "implicit",
        "import",
        "lazy",
        "match",
        "new",
        "null",
        "object",
        "override",
        "package",
        "private",
        "protected",
        "return",
        "sealed",
        "super",
        "this",
        "throw",
        "trait",
        "true",
        "try",
        "type",
        "val",
        "var",
        "while",
        "with",
        "yield",
    }

    if field_name in scala_keywords:
        return f"`{field_name}`"

    return field_name


def _generate_column_aliases(fields: list[FieldInfo]) -> str:
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

        # This field has an alias different from its name
        escaped_field_name = _escape_scala_keyword(field.name)
        alias_lines.append(f'      col("{field.alias}").alias("{field.name}")')
        has_aliases = True

    if not has_aliases:
        return "    val df_aliased = df\n"

    # Generate the select statement with aliases
    alias_select = ",\n".join(alias_lines)
    return f"""    val df_aliased = df.select(
      col("*"),  // Select all existing columns
{alias_select}
    ).drop({", ".join(f'"{field.alias}"' for field in fields if field.alias and field.alias != field.name and not field.name.startswith("<") and "." not in field.name)})  // Drop original aliased columns to avoid duplicates
"""


def _generate_filter_methods(
    trait_name: str, discriminator: str, variants: list[type[BaseModel]]
) -> str:
    """Generate type-safe filter methods for each variant."""
    methods = []
    for variant in variants:
        discriminator_value = _get_discriminator_value(variant, discriminator)
        method = f"""  def filter{variant.__name__}s(ds: Dataset[{trait_name}]): Dataset[{variant.__name__}] = {{
    ds.filter(col("{discriminator}") === "{discriminator_value}")
      .map(_.asInstanceOf[{variant.__name__}])
  }}"""
        methods.append(method)

    return "\n\n".join(methods)
