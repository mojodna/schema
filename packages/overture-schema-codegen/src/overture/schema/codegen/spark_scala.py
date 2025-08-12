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

        # Handle default values - skip PydanticUndefined and type mismatches
        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = _format_scala_default_value(field.default_value, scala_type)
            if default_str is not None:  # Only add default if it's type-compatible
                scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
            else:
                scala_fields.append(f"  {field_name}: {scala_type}")
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
            field.annotation, field.is_nullable, field.name
        )

        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = _format_scala_default_value(field.default_value, scala_type)
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
            field.annotation, field.is_nullable, field.name
        )

        if (
            field.default_value is not None
            and str(field.default_value) != "PydanticUndefined"
        ):
            default_str = _format_scala_default_value(field.default_value, scala_type)
            if default_str is not None:  # Only add default if it's type-compatible
                scala_fields.append(f"  {field_name}: {scala_type} = {default_str}")
            else:
                scala_fields.append(f"  {field_name}: {scala_type}")
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

        # Handle nested structures - only use nested_model if it's a direct BaseModel field
        if field.nested_model and _is_direct_base_model(field.annotation):
            spark_type = _generate_struct_type_for_model(field.nested_model)
        else:
            spark_type = _map_python_type_to_spark_type_with_nested(
                field.annotation, schema_field_name
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


def _is_direct_base_model(annotation: Any) -> bool:
    """Check if the annotation is directly a BaseModel (not nested in collections)."""
    # Handle Annotated types
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return _is_direct_base_model(actual_type)

    # Check if it's directly a BaseModel class
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)


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
    """Generate Spark-compatible flattened case class for discriminated union."""

    # Generate flattened case class name from variants
    flattened_name = _generate_trait_name([v.__name__ for v in variants])

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
                # New field - make it optional since it won't exist in all variants
                scala_type = _map_python_type_to_spark_scala(
                    field.annotation,
                    True,
                    field.name,  # Force nullable for variant-specific fields
                )

                all_fields[field_name] = {
                    "scala_type": scala_type,
                    "is_nullable": True,  # Always nullable in flattened approach
                    "default_value": None,  # Default to None for variant-specific fields
                    "alias": field.alias,
                    "spark_type": _map_python_type_to_spark_type(
                        field.annotation, field.name
                    ),
                }

                # Add to schema fields
                schema_field_name = field.alias if field.alias else field.name
                all_schema_fields.append(
                    {
                        "name": schema_field_name,
                        "type": _map_python_type_to_spark_type(
                            field.annotation, schema_field_name
                        ),
                        "nullable": True,  # Always nullable in flattened approach
                    }
                )

    # Generate flattened case class fields
    scala_fields = []
    for field_name, field_info in all_fields.items():
        escaped_name = _escape_scala_keyword(field_name)
        scala_type = field_info["scala_type"]

        if field_name == discriminator:
            # Discriminator field is required
            scala_fields.append(f"  {escaped_name}: {scala_type}")
        else:
            # All variant-specific fields are optional with None default
            scala_fields.append(f"  {escaped_name}: {scala_type} = None")

    fields_str = ",\n".join(scala_fields)

    # Generate schema fields
    schema_fields_str = _generate_schema_fields_from_list(all_schema_fields, "      ")

    # Generate column aliases for fields that have them
    alias_mappings = _generate_column_aliases_for_flattened(all_fields)

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
        nested_case_class = _generate_simple_case_class(nested_model)
        nested_case_classes.append(nested_case_class)

    # Generate narrowed case classes for each variant
    narrowed_case_classes = _generate_narrowed_case_classes(
        variants, discriminator, all_fields
    )

    # Generate filter methods for each variant (returning narrowed types using .as[])
    filter_methods = _generate_simple_filter_methods_with_casting(
        flattened_name, discriminator, variants
    )

    # Generate narrowed case classes as a string to include before flattened case class
    narrowed_classes_str = "\n\n".join(narrowed_case_classes) if narrowed_case_classes else ""
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

{_generate_conversion_methods(flattened_name, discriminator, variants, all_fields)}
}}"""

    # Combine everything with nested case classes first
    result = package_line + imports_section
    if nested_case_classes:
        result += "\n".join(nested_case_classes) + "\n\n"
    result += flattened_case_class

    return result


def _map_python_type_to_spark_scala(
    python_type: type, is_nullable: bool = False, field_name: str = ""
) -> str:
    """Map Python types to Spark-compatible Scala types using abstract type information."""
    # Special case for geometry field - always Array[Byte] for binary data
    if field_name == "geometry":
        return "Array[Byte]" if not is_nullable else "Option[Array[Byte]]"

    # Handle NewType by checking the underlying type first
    if hasattr(python_type, "__supertype__"):
        underlying_type = python_type.__supertype__
        return _map_python_type_to_spark_scala(underlying_type, is_nullable, field_name)

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return _map_python_type_to_spark_scala(actual_type, is_nullable, field_name)

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
            return _map_python_type_to_spark_scala(non_none_type, True, field_name)

    # Handle collections
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_scala = _map_python_type_to_spark_scala(inner_type, False, "")
        scala_type = f"Array[{inner_scala}]"
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type
    elif origin is dict:
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = _map_python_type_to_spark_scala(args[0], False, "")
            value_type = _map_python_type_to_spark_scala(args[1], False, "")
            scala_type = f"Map[{key_type}, {value_type}]"
        else:
            scala_type = "Map[String, String]"  # Default fallback
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type

    # Check if this is a BaseModel (nested structure)
    if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        scala_type = python_type.__name__
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type

    # Try to get target type from abstract type system
    scala_type = get_target_type(python_type, "scala")
    if scala_type:
        # Wrap with Option if nullable
        if is_nullable and not scala_type.startswith("Option["):
            scala_type = f"Option[{scala_type}]"
        return scala_type

    # Ultimate fallback
    scala_type = "String"
    if is_nullable:
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


def _format_scala_default_value(default_value: Any, scala_type: str) -> str | None:
    """Format Python default values as Scala literals with type awareness."""
    # Skip invalid defaults (PydanticUndefined should not reach here)
    if str(default_value) == "PydanticUndefined":
        return None

    is_optional = scala_type.startswith("Option[")

    # Handle None values
    if default_value is None:
        return "None" if is_optional else "null"

    # Handle list/array defaults
    if isinstance(default_value, list):
        if not default_value:  # Empty list
            if "Array[" in scala_type:
                base_array = "Array.empty"
                return f"Some({base_array})" if is_optional else base_array
            else:
                # Type mismatch - don't provide a default that won't compile
                return None

        # Non-empty list - need to format items based on inner type
        if "Array[" in scala_type:
            items = ", ".join(
                f'"{item}"' if isinstance(item, str) else str(item)
                for item in default_value
            )
            array_str = f"Array({items})"
            return f"Some({array_str})" if is_optional else array_str
        else:
            # Type mismatch - don't provide incompatible defaults
            return None

    # Handle string defaults
    elif isinstance(default_value, str):
        if (
            "String" in scala_type
            or scala_type == "String"
            or (is_optional and "String" in scala_type)
        ):
            quoted = f'"{default_value}"'
            return f"Some({quoted})" if is_optional else quoted
        else:
            # Type mismatch - don't provide incompatible defaults
            return None

    # Handle boolean defaults
    elif isinstance(default_value, bool):
        if "Boolean" in scala_type or (is_optional and "Boolean" in scala_type):
            bool_str = str(default_value).lower()
            return f"Some({bool_str})" if is_optional else bool_str
        else:
            return None

    # Handle numeric defaults
    elif isinstance(default_value, (int, float)):
        if (
            "Int" in scala_type
            or "Long" in scala_type
            or "Double" in scala_type
            or "Float" in scala_type
        ):
            if isinstance(default_value, int) and "Long" in scala_type:
                val_str = f"{default_value}L"
            else:
                val_str = str(default_value)
            return f"Some({val_str})" if is_optional else val_str
        else:
            return None

    # For unknown types, don't provide a default that might not compile
    return None


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
        spark_type = _map_python_type_to_spark_type(field.annotation, schema_field_name)
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
    """Escape Scala reserved keywords and invalid identifiers using backticks or transformation."""
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

    # Handle identifiers ending with underscore (generally invalid in Scala)
    if field_name.endswith("_") and len(field_name) > 1:
        return f"`{field_name}`"

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


def _generate_column_aliases_for_flattened(all_fields: dict) -> str:
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


def _generate_flattened_filter_methods(
    flattened_name: str, discriminator: str, variants: list[type[BaseModel]]
) -> str:
    """Generate filter methods for each variant in flattened approach."""
    methods = []
    for variant in variants:
        discriminator_value = _get_discriminator_value(variant, discriminator)
        method = f"""  def filter{variant.__name__}s(ds: Dataset[{flattened_name}]): Dataset[{flattened_name}] = {{
    ds.filter(col("{discriminator}") === "{discriminator_value}")
  }}"""
        methods.append(method)

    return "\n\n".join(methods)


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


def _generate_simple_filter_methods_with_casting(
    flattened_name: str, discriminator: str, variants: list
) -> str:
    """Generate filter methods that return narrowed types using .as[] casting."""
    methods = []
    for variant in variants:
        discriminator_value = _get_discriminator_value(variant, discriminator)
        method = f"""  def filter{variant.__name__}s(ds: Dataset[{flattened_name}]): Dataset[{variant.__name__}] = {{
    ds.filter(col("{discriminator}") === "{discriminator_value}").as[{variant.__name__}]
  }}"""
        methods.append(method)

    return "\n\n".join(methods)


def _generate_narrowed_case_classes(
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

            field_name = _escape_scala_keyword(field.name)
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

def _generate_conversion_methods(
    flattened_name: str, discriminator: str, variants: list[type[BaseModel]], all_fields: dict
) -> str:
    """Generate conversion methods from flattened to narrowed types."""
    methods = []

    for variant in variants:
        discriminator_value = _get_discriminator_value(variant, discriminator)
        variant_fields = extract_fields_recursive(variant)

        # Build field assignments for conversion
        field_assignments = []
        for field in variant_fields:
            if field.name.startswith("<") or "." in field.name:
                continue
            if field.name == discriminator:
                continue

            field_name = _escape_scala_keyword(field.name)
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
