"""Scala code formatting and utility functions."""

from typing import Any

from pydantic import BaseModel


def format_scala_default_value(default_value: Any, scala_type: str) -> str | None:
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


def escape_scala_keyword(field_name: str) -> str:
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


def generate_trait_name(variant_names: list[str]) -> str:
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


def get_discriminator_value(
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
