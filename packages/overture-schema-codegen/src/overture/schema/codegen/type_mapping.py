"""Type mapping utilities for converting Python types to Spark Scala and Spark SQL types."""

import inspect
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import BaseModel

try:
    from overture.schema.core.types.abstract import get_target_type
except ImportError:
    # Fallback if abstract types are not available
    def get_target_type(abstract_type, target):
        return None


def map_python_type_to_spark_scala(
    python_type: type, is_nullable: bool = False, field_name: str = ""
) -> str:
    """Map Python types to Spark-compatible Scala types using abstract type information."""
    # Special case for geometry field - always Array[Byte] for binary data
    if field_name == "geometry":
        return "Array[Byte]" if not is_nullable else "Option[Array[Byte]]"

    # Handle NewType by checking the underlying type first
    if hasattr(python_type, "__supertype__"):
        underlying_type = python_type.__supertype__
        return map_python_type_to_spark_scala(underlying_type, is_nullable, field_name)

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return map_python_type_to_spark_scala(actual_type, is_nullable, field_name)

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
            return map_python_type_to_spark_scala(non_none_type, True, field_name)

    # Handle collections
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_scala = map_python_type_to_spark_scala(inner_type, False, "")
        scala_type = f"Array[{inner_scala}]"
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type
    elif origin is dict:
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = map_python_type_to_spark_scala(args[0], False, "")
            value_type = map_python_type_to_spark_scala(args[1], False, "")
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


def map_python_type_to_spark_scala_with_nested(
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
        return map_python_type_to_spark_scala_with_nested(
            underlying_type, is_nullable, field_name
        )

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return map_python_type_to_spark_scala_with_nested(
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
            return map_python_type_to_spark_scala_with_nested(
                non_none_type, True, field_name
            )

    # Handle collections before falling back
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_scala = map_python_type_to_spark_scala_with_nested(inner_type, False, "")
        scala_type = f"Array[{inner_scala}]"
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type
    elif origin is dict:
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = map_python_type_to_spark_scala_with_nested(args[0], False, "")
            value_type = map_python_type_to_spark_scala_with_nested(args[1], False, "")
            scala_type = f"Map[{key_type}, {value_type}]"
        else:
            scala_type = "Map[String, String]"  # Default fallback
        if is_nullable:
            scala_type = f"Option[{scala_type}]"
        return scala_type

    # Fall back to original mapping
    return map_python_type_to_spark_scala(python_type, is_nullable, field_name)


def map_python_type_to_spark_type(python_type: type, field_name: str = "") -> str:
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
        inner_spark = map_python_type_to_spark_type(inner_type, "")
        return f"ArrayType({inner_spark})"
    elif origin is dict:
        return "MapType(StringType, StringType)"

    # Fallback to get_target_type for basic Python types
    spark_type_result = get_target_type(python_type, "spark")
    return spark_type_result if spark_type_result else "StringType"  # Ultimate fallback


def map_python_type_to_spark_type_with_nested(
    python_type: type, field_name: str = ""
) -> str:
    """Map Python types to Spark SQL types using abstract type information, handling nested structures."""
    # Check if this is a BaseModel (nested structure)
    if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        return generate_struct_type_for_model(python_type)

    # Handle NewType by checking the underlying type
    if hasattr(python_type, "__supertype__"):
        underlying_type = python_type.__supertype__
        return map_python_type_to_spark_type_with_nested(underlying_type, field_name)

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return map_python_type_to_spark_type_with_nested(actual_type, field_name)

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
            return map_python_type_to_spark_type_with_nested(non_none_type, field_name)

    # Handle collections
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_spark = map_python_type_to_spark_type_with_nested(inner_type, "")
        return f"ArrayType({inner_spark})"
    elif origin is dict:
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = map_python_type_to_spark_type_with_nested(args[0], "")
            value_type = map_python_type_to_spark_type_with_nested(args[1], "")
            return f"MapType({key_type}, {value_type})"
        else:
            return "MapType(StringType, StringType)"  # Default fallback

    # Fall back to original mapping
    return map_python_type_to_spark_type(python_type, field_name)


def generate_struct_type_for_model(model_class: type[BaseModel]) -> str:
    """Generate a StructType definition for a nested Pydantic model."""
    struct_fields = []

    for field_name, field_info in model_class.model_fields.items():
        field_type = map_python_type_to_spark_type_with_nested(
            field_info.annotation, field_name
        )
        nullable = str(is_nullable_annotation(field_info.annotation)).lower()
        struct_fields.append(f'StructField("{field_name}", {field_type}, {nullable})')

    return f"StructType(Array({', '.join(struct_fields)}))"


def is_nullable_annotation(annotation: Any) -> bool:
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


def is_direct_base_model(annotation: Any) -> bool:
    """Check if the annotation is directly a BaseModel (not nested in collections)."""
    # Handle Annotated types
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return is_direct_base_model(actual_type)

    # Check if it's directly a BaseModel class
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)
