"""Foreign key utilities for type-safe relationships between Overture features."""

from typing import (
    TYPE_CHECKING,
    Annotated,
    Generic,
    Literal,
    NewType,
    TypeVar,
    get_args,
    get_origin,
)

from pydantic import Field, GetJsonSchemaHandler
from pydantic_core import core_schema

from .types import Id

if TYPE_CHECKING:
    from typing import Any

# Type variables for foreign key relationships
SourceT = TypeVar("SourceT")  # The type that contains the foreign key
TargetT = TypeVar("TargetT")  # The type that the foreign key references


class ForeignKey(Generic[SourceT, TargetT]):
    """A typed foreign key that references another feature type.

    This creates a type-safe foreign key relationship where:
    - SourceT: The feature type that contains this foreign key
    - TargetT: The feature type that this foreign key references

    Examples:
        # Reference to a connector from a segment
        connector_id: ForeignKey[Literal["segment"], Literal["connector"]] = ForeignKey("connector_123")

        # Reference to a building from a building part
        building_id: ForeignKey[Literal["building_part"], Literal["building"]] = ForeignKey("building_456")
    """

    def __class_getitem__(cls, params: tuple) -> type:  # type: ignore
        """Create a parameterized ForeignKey type."""
        if not isinstance(params, tuple) or len(params) != 2:
            raise TypeError(
                "ForeignKey requires exactly two type parameters: ForeignKey[SourceT, TargetT]"
            )

        source_type, target_type = params
        type_name = "ForeignKey"  # Use a literal string for mypy

        # Create a NewType that carries the relationship information
        fk_type = NewType(
            type_name,
            Annotated[
                Id,
                Field(
                    description=f"Foreign key reference from {source_type} to {target_type}",
                    json_schema_extra={
                        "x-foreign-key": {
                            "source": str(source_type),
                            "target": str(target_type),
                            "relationship": "references",
                        }
                    },
                ),
            ],
        )

        # Add relationship metadata as attributes
        fk_type._source_type = source_type  # type: ignore
        fk_type._target_type = target_type  # type: ignore

        return fk_type  # type: ignore

    def __new__(cls, value: str) -> "ForeignKey[SourceT, TargetT]":  # type: ignore
        """Allow direct instantiation for runtime usage."""
        return value  # type: ignore


def References(target_type: type) -> type:  # type: ignore
    """Simplified foreign key that just specifies the target type.

    This is a convenience function for cases where you don't need to specify
    the source type explicitly.

    Args:
        target_type: The type that this foreign key references

    Returns:
        A type that can be used for foreign key annotations

    Examples:
        # Note: Use as a type alias, not as a function call in annotations
        ConnectorId = References(Literal["connector"])
        connector_id: ConnectorId = "connector_123"
    """
    type_name = "References"  # Use literal string for mypy
    return NewType(
        type_name,
        Annotated[
            Id,
            Field(
                description=f"Foreign key reference to {target_type}",
                json_schema_extra={
                    "x-foreign-key": {
                        "target": str(target_type),
                        "relationship": "references",
                    }
                },
            ),
        ],
    )


def _extract_foreign_keys_from_type(type_annotation: type) -> list[dict[str, str]]:
    """Recursively extract foreign keys from a type annotation, including nested generics."""
    results = []

    # Direct foreign key check
    fk_info = get_foreign_key_info(type_annotation)
    if fk_info:
        results.append(fk_info)

    # Check for generic types (like list, dict, etc.) and recurse into their arguments
    if hasattr(type_annotation, "__origin__") and hasattr(type_annotation, "__args__"):
        for arg in type_annotation.__args__:
            results.extend(_extract_foreign_keys_from_type(arg))
    elif get_origin(type_annotation) is not None:
        for arg in get_args(type_annotation):
            results.extend(_extract_foreign_keys_from_type(arg))

    return results


def get_foreign_key_info(field_type: type) -> dict[str, str] | None:
    """Extract foreign key relationship information from a field type.

    Args:
        field_type: The type to analyze

    Returns:
        Dictionary with foreign key info or None if not a foreign key
    """
    # Check if this is a References type by name pattern
    if hasattr(field_type, "__name__"):
        name = field_type.__name__
        if name.startswith("References[") and name.endswith("]"):
            # Extract the target type from the name
            target_part = name[len("References[") : -1]
            return {"target": target_part, "relationship": "references"}
        elif name.startswith("ForeignKey[") and name.endswith("]"):
            # Extract both source and target from the name
            params_part = name[len("ForeignKey[") : -1]
            if ", " in params_part:
                source_part, target_part = params_part.split(", ", 1)
                return {
                    "source": source_part,
                    "target": target_part,
                    "relationship": "references",
                }

    # Check if this is a ForeignKey type with attributes
    if hasattr(field_type, "_source_type") and hasattr(field_type, "_target_type"):
        return {
            "source": str(field_type._source_type),
            "target": str(field_type._target_type),
            "relationship": "references",
        }

    # Check for metadata in supertype (for Annotated types)
    if hasattr(field_type, "__supertype__"):
        for metadata in getattr(field_type.__supertype__, "__metadata__", []):
            if hasattr(metadata, "json_schema_extra") and metadata.json_schema_extra:
                fk_info = metadata.json_schema_extra.get("x-foreign-key")
                if fk_info:
                    return fk_info

    return None


def get_relationships_from_model(model_class: type) -> dict[str, list[dict[str, str]]]:
    """Extract all foreign key relationships from a Pydantic model.

    Args:
        model_class: The Pydantic model class to analyze

    Returns:
        Dictionary mapping field names to list of their foreign key information
        (list because a field might contain multiple foreign keys, e.g., in generics)
    """
    relationships = {}

    if hasattr(model_class, "model_fields"):
        for field_name, field_info in model_class.model_fields.items():
            if hasattr(field_info, "annotation"):
                fk_infos = _extract_foreign_keys_from_type(field_info.annotation)
                if fk_infos:
                    relationships[field_name] = fk_infos

    return relationships


# Export the main types
__all__ = [
    "ForeignKey",
    "References",
    "get_foreign_key_info",
    "get_relationships_from_model",
]
