from typing import Any, NewType

from .abstract_type import AbstractType, AbstractTypeDefinition, AbstractTypeRegistry

UInt8 = NewType("UInt8", AbstractType["UINT8"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821
UInt16 = NewType("UInt16", AbstractType["UINT16"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821
UInt32 = NewType("UInt32", AbstractType["UINT32"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821

Int8 = NewType("Int8", AbstractType["INT8"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821
Int32 = NewType("Int32", AbstractType["INT32"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821
Int64 = NewType("Int64", AbstractType["INT64"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821

Float32 = NewType("Float32", AbstractType["FLOAT32"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821
Float64 = NewType("Float64", AbstractType["FLOAT64"])  # type: ignore[misc,name-defined,type-arg] # noqa: F821


# Utility functions for easy access
def get_target_type(concrete_type: type[Any], language: str) -> str | None:
    """Get target language type for a concrete type."""
    abstract_type_def = get_abstract_type(concrete_type)
    if abstract_type_def:
        return abstract_type_def.target_mappings.get(language)

    # Direct lookup in registry for basic types and classes
    if concrete_type in AbstractTypeRegistry.TYPES:
        return AbstractTypeRegistry.TYPES[concrete_type].target_mappings.get(language)

    return None


def get_abstract_type(
    concrete_type: type[Any],
) -> AbstractTypeDefinition | None:
    """Get the abstract type definition for a concrete type."""
    from typing import Annotated, get_args, get_origin

    # For NewType with Annotated, check if it has __metadata__
    if hasattr(concrete_type, "__metadata__"):
        for item in concrete_type.__metadata__:
            if isinstance(item, AbstractTypeDefinition):
                return item

    # Handle Annotated types (e.g., Annotated[Int32, FieldInfo(...)])
    origin = get_origin(concrete_type)
    if origin is Annotated:
        args = get_args(concrete_type)
        if args:
            # Recursively check the first type argument (the actual type)
            return get_abstract_type(args[0])

    # For NewType, check if __supertype__ has metadata
    if hasattr(concrete_type, "__supertype__"):
        return get_abstract_type(concrete_type.__supertype__)

    # Direct lookup in registry for class-based types
    return AbstractTypeRegistry.TYPES.get(concrete_type)
