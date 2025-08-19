"""Type mapping utilities for converting Python types to Spark Scala and Spark SQL types."""

import inspect
import re
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel

try:
    from overture.schema.core.types.abstract import get_target_type
except ImportError:
    # Fallback if abstract types are not available
    def get_target_type(abstract_type, target):
        return None


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    # Insert underscore before uppercase letters that follow lowercase letters or digits
    s1 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
    # Insert underscore before uppercase letters that are followed by lowercase letters
    s2 = re.sub("([A-Z])([A-Z][a-z])", r"\1_\2", s1)
    return s2.lower()


def _extract_theme_from_enum(enum_class: type[Any]) -> str | None:
    """Extract theme name from an Enum class based on its module path."""
    if hasattr(enum_class, "__module__"):
        module_parts = enum_class.__module__.split(".")
        for part in module_parts:
            if part.endswith("-theme") or part in [
                "transportation",
                "buildings",
                "places",
                "addresses",
                "base",
                "divisions",
            ]:
                return part.replace("-theme", "")
    return None


def _get_enum_link_path(enum_class: type[Any], current_theme: str | None = None) -> str:
    """Generate the correct relative path for an enum link."""
    enum_theme = _extract_theme_from_enum(enum_class)
    snake_case_name = _to_snake_case(enum_class.__name__)

    # If both are in the same theme or enum has no theme (root level)
    if enum_theme == current_theme or enum_theme is None:
        if current_theme is None:
            # Both in root
            return snake_case_name
        elif enum_theme is None:
            # Enum in root, current in theme - need to go up one level
            return f"../{snake_case_name}"
        else:
            # Both in same theme
            return snake_case_name
    else:
        # Different themes - need to navigate between theme directories
        if current_theme is None:
            # Current in root, enum in theme
            return f"{enum_theme}/{snake_case_name}"
        else:
            # Both in different themes
            return f"../{enum_theme}/{snake_case_name}"


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


def get_enum_examples(enum_class: type, max_examples: int = 3) -> list[str]:
    """Extract the first N enum values as examples.

    Args:
        enum_class: The enum class to extract values from
        max_examples: Maximum number of examples to return (default: 3)

    Returns:
        List of enum values as strings
    """
    try:
        import enum

        if not (inspect.isclass(enum_class) and issubclass(enum_class, enum.Enum)):
            return []

        # Get all enum values
        enum_values = []
        for member in enum_class:
            if hasattr(member, "value"):
                enum_values.append(str(member.value))
            else:
                enum_values.append(str(member))

        # Return first max_examples values
        return enum_values[:max_examples]

    except (ImportError, TypeError, AttributeError):
        return []


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


def _map_python_type_to_documented_without_backticks(
    python_type: type, is_nullable: bool = False, field_name: str = ""
) -> str:
    """Map Python types to human-readable documented types without backticks."""
    # This is a helper function that doesn't add backticks around types
    # Used for inner types within Array[] or Record<> syntax

    # FIRST: Try to get target type from abstract type system before doing anything else
    documented_type = get_target_type(python_type, "documented")
    if documented_type:
        return f"{documented_type} (optional)" if is_nullable else documented_type

    # Handle NewType by checking the underlying type first
    if hasattr(python_type, "__supertype__"):
        underlying_type = python_type.__supertype__
        return _map_python_type_to_documented_without_backticks(
            underlying_type, is_nullable, field_name
        )

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return _map_python_type_to_documented_without_backticks(
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
            base_type = _map_python_type_to_documented_without_backticks(
                non_none_type, False, field_name
            )
            return f"{base_type} (optional)" if not is_nullable else base_type

        # For other unions, show all variants
        variant_types = [
            _map_python_type_to_documented_without_backticks(arg, False, "")
            for arg in args
            if arg is not type(None)
        ]
        return " | ".join(variant_types)

    # Handle Literal types
    if origin is Literal:
        args = get_args(python_type)
        if args:
            # Format literal values for display (no backticks)
            if len(args) == 1:
                # Single literal value
                literal_value = args[0]
                if hasattr(literal_value, "value"):
                    # Handle enum values in Literal
                    base_type = f'"{literal_value.value}"'
                else:
                    base_type = f'"{literal_value}"'
            else:
                # Multiple literal values
                formatted_values = []
                for value in args:
                    if hasattr(value, "value"):
                        formatted_values.append(f'"{value.value}"')
                    else:
                        formatted_values.append(f'"{value}"')
                base_type = " | ".join(formatted_values)

            return f"{base_type} (optional)" if is_nullable else base_type

    # Check if this is a BaseModel (nested structure)
    if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        snake_case_name = _to_snake_case(python_type.__name__)
        base_type = f"object (`[{python_type.__name__}]({snake_case_name})`)"
        return f"{base_type} (optional)" if is_nullable else base_type

    # Check if this is an enum
    try:
        import enum

        if inspect.isclass(python_type) and issubclass(python_type, enum.Enum):
            # Check if it's a string enum (inherits from str, Enum)
            snake_case_name = _to_snake_case(python_type.__name__)
            if issubclass(python_type, str):
                base_type = f"string ([{python_type.__name__}]({snake_case_name}))"
            else:
                base_type = f"[{python_type.__name__}]({snake_case_name})"
            return f"{base_type} (optional)" if is_nullable else base_type
    except (ImportError, TypeError):
        pass

    # Ultimate fallback - use the class name or string representation (no backticks)
    if hasattr(python_type, "__name__"):
        base_type = python_type.__name__
    else:
        base_type = str(python_type)

    return f"{base_type} (optional)" if is_nullable else base_type


def map_python_type_to_documented(
    python_type: type,
    is_nullable: bool = False,
    field_name: str = "",
    current_theme: str | None = None,
) -> str:
    """Map Python types to human-readable documented types."""
    # Handle arrays/lists in field paths - not part of this function
    # This function maps individual Python types to documented type names

    # FIRST: Try to get target type from abstract type system before doing anything else
    documented_type = get_target_type(python_type, "documented")
    if documented_type:
        return (
            f"`{documented_type}` (optional)" if is_nullable else f"`{documented_type}`"
        )

    # Handle NewType by checking the underlying type first
    if hasattr(python_type, "__supertype__"):
        underlying_type = python_type.__supertype__
        return map_python_type_to_documented(
            underlying_type, is_nullable, field_name, current_theme
        )

    # Handle Annotated types
    origin = get_origin(python_type)
    if origin is Annotated:
        args = get_args(python_type)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return map_python_type_to_documented(
                actual_type, is_nullable, field_name, current_theme
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
            base_type = map_python_type_to_documented(
                non_none_type, False, field_name, current_theme
            )
            return f"{base_type} (optional)" if not is_nullable else base_type

        # For other unions, show all variants
        variant_types = [
            map_python_type_to_documented(arg, False, "", current_theme)
            for arg in args
            if arg is not type(None)
        ]
        return " | ".join(variant_types)

    # Handle collections
    if origin is list:
        args = get_args(python_type)
        inner_type = args[0] if args else str
        inner_documented = _map_python_type_to_documented_without_backticks(
            inner_type, False, ""
        )
        # Check if inner type contains links (contains markdown links)
        if "](" in inner_documented:
            # Format as `list<`inner_type`>` to allow links to render properly
            base_type = f"`list<{inner_documented}>`"
        else:
            # Regular formatting with backticks around the whole thing
            base_type = f"`list<{inner_documented}>`"
        return f"{base_type} (optional)" if is_nullable else base_type
    elif origin is dict:
        args = get_args(python_type)
        if len(args) >= 2:
            key_type = _map_python_type_to_documented_without_backticks(
                args[0], False, ""
            )
            value_type = _map_python_type_to_documented_without_backticks(
                args[1], False, ""
            )
            # For string-to-string mappings, use simple "Object"
            if key_type.lower() == "string" and value_type.lower() == "string":
                base_type = "`object`"
            else:
                base_type = f"`record<{key_type}, {value_type}>`"
        else:
            base_type = "`object`"  # Default fallback for string-to-string
        return f"{base_type} (optional)" if is_nullable else base_type

    # Handle Literal types
    if origin is Literal:
        args = get_args(python_type)
        if args:
            # Format literal values for display
            if len(args) == 1:
                # Single literal value
                literal_value = args[0]
                if hasattr(literal_value, "value"):
                    # Handle enum values in Literal
                    base_type = f'`"{literal_value.value}"`'
                else:
                    base_type = f'`"{literal_value}"`'
            else:
                # Multiple literal values
                formatted_values = []
                for value in args:
                    if hasattr(value, "value"):
                        formatted_values.append(f'"{value.value}"')
                    else:
                        formatted_values.append(f'"{value}"')
                base_type = f"`{' | '.join(formatted_values)}`"

            return f"{base_type} (optional)" if is_nullable else base_type

    # Check if this is a BaseModel (nested structure)
    if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
        snake_case_name = _to_snake_case(python_type.__name__)
        base_type = f"`object` (`[{python_type.__name__}]({snake_case_name})`)"
        return f"{base_type} (optional)" if is_nullable else base_type

    # Check if this is an enum
    try:
        import enum

        if inspect.isclass(python_type) and issubclass(python_type, enum.Enum):
            # Check if it's a string enum (inherits from str, Enum)
            enum_link_path = _get_enum_link_path(python_type, current_theme)
            if issubclass(python_type, str):
                base_type = f"`string` ([{python_type.__name__}]({enum_link_path}))"
            else:
                base_type = f"[{python_type.__name__}]({enum_link_path})"

            return f"{base_type} (optional)" if is_nullable else base_type
    except (ImportError, TypeError):
        pass

    # Ultimate fallback - use the class name or string representation
    if hasattr(python_type, "__name__"):
        base_type = f"`{python_type.__name__}`"
    else:
        base_type = f"`{str(python_type)}`"

    return f"{base_type} (optional)" if is_nullable else base_type
