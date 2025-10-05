"""Type introspection and structural analysis for union types."""

import inspect
from dataclasses import dataclass
from typing import Annotated as AnnotatedType
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

# Type aliases for structural tuple elements
StructuralElement = Literal["list_index", "union", "model", "discriminator", "field"]


@dataclass
class UnionMetadata:
    """Metadata about a union type's structure."""

    is_discriminated: bool
    discriminator_field: str | None
    # Map discriminator values to their corresponding model types
    discriminator_to_model: dict[str, type[BaseModel]]
    # Map model class names to their types (for non-discriminated unions)
    model_name_to_model: dict[str, type[BaseModel]]
    # Nested union metadata for union members that are themselves unions
    nested_unions: dict[str, "UnionMetadata"]


def introspect_union(union_type: Any) -> UnionMetadata:  # noqa: ANN401
    """Introspect a union type to extract structural information.

    Args:
        union_type: A union type (may be Annotated with discriminator)

    Returns:
        UnionMetadata describing the structure of the union
    """
    # Check if this is a list type - unwrap to get the element type
    origin = get_origin(union_type)
    if origin is list:
        args = get_args(union_type)
        if args:
            # Recursively introspect the list element type
            return introspect_union(args[0])

    # Check if this is an Annotated type with a discriminator
    discriminator_field = None
    actual_union = union_type

    # Unwrap Annotated ONLY if the top level is Annotated
    if origin is AnnotatedType:
        # This is Annotated[Union[...], ...]
        args = get_args(union_type)
        if args:
            # First arg is the actual type, rest are metadata
            actual_union = args[0]
            # Look for Field with discriminator in metadata
            for metadata in args[1:]:
                if isinstance(metadata, FieldInfo) and hasattr(
                    metadata, "discriminator"
                ):
                    discriminator_field = metadata.discriminator
                    break

    # Get union members
    union_origin = get_origin(actual_union)
    if union_origin is None:
        # Not a union, might be a single model
        union_members = [actual_union]
    else:
        union_members = list(get_args(actual_union))

    discriminator_to_model: dict[str, type[BaseModel]] = {}
    model_name_to_model: dict[str, type[BaseModel]] = {}
    nested_unions: dict[str, UnionMetadata] = {}

    # Analyze each union member
    for member in union_members:
        # Check if member is itself annotated (nested discriminated union)
        member_origin = get_origin(member)

        # If it's an Annotated type, it might contain a discriminated union
        if member_origin is AnnotatedType:
            # Check if this is an Annotated with a discriminator
            member_args = get_args(member)
            if member_args:
                # Check for Field with discriminator in the annotations
                has_discriminator = False
                for metadata in member_args[1:]:
                    if isinstance(metadata, FieldInfo) and hasattr(
                        metadata, "discriminator"
                    ):
                        has_discriminator = True
                        break

                if has_discriminator:
                    # This is a nested discriminated union
                    nested_metadata = introspect_union(member)
                    nested_unions[str(member)] = nested_metadata
                    # Also extract discriminator mappings from the nested union
                    discriminator_to_model.update(
                        nested_metadata.discriminator_to_model
                    )
                    continue

                # Check if the inner type is a union (could be Union without Annotated)
                inner_type = member_args[0]
                if get_origin(inner_type) is not None:
                    # Nested union without discriminator at this level
                    nested_metadata = introspect_union(member)
                    nested_unions[str(member)] = nested_metadata
                    discriminator_to_model.update(
                        nested_metadata.discriminator_to_model
                    )
                    continue

        # It's a BaseModel
        if inspect.isclass(member) and issubclass(member, BaseModel):
            model_name_to_model[member.__name__] = member

            # Extract discriminator values from ALL Literal fields (not just the current discriminator)
            # This handles nested discriminators with different field names
            for _field_name, field_info in member.model_fields.items():
                annotation = field_info.annotation
                literal_origin = get_origin(annotation)
                if literal_origin is Literal:
                    literal_args = get_args(annotation)
                    if literal_args:
                        disc_value = literal_args[0]
                        discriminator_to_model[disc_value] = member

    return UnionMetadata(
        is_discriminated=discriminator_field is not None,
        discriminator_field=discriminator_field,
        discriminator_to_model=discriminator_to_model,
        model_name_to_model=model_name_to_model,
        nested_unions=nested_unions,
    )


def create_structural_tuple(
    loc: tuple[str | int, ...],
    metadata: UnionMetadata,
) -> tuple[StructuralElement, ...]:
    """Create a structural tuple parallel to error['loc'] describing each element.

    Args:
        loc: The location tuple from a Pydantic validation error
        metadata: Pre-computed UnionMetadata from introspect_union()

    Returns:
        Tuple of same length as loc with structural labels for each element
    """
    structural: list[StructuralElement] = []

    i = 0
    while i < len(loc):
        element = loc[i]

        # Check if it's a list index (integer)
        if isinstance(element, int):
            structural.append("list_index")
            i += 1
            continue

        # Check if it's a union marker string
        if isinstance(element, str) and element.startswith("tagged-union["):
            structural.append("union")
            i += 1
            # After a union marker, expect discriminator value(s)
            # Continue to identify following discriminator elements
            continue

        # Check if it's a model class name (non-discriminated union member)
        if isinstance(element, str) and element in metadata.model_name_to_model:
            structural.append("model")
            i += 1
            continue

        # Check if it's a discriminator value (can come from nested unions)
        if isinstance(element, str) and element in metadata.discriminator_to_model:
            structural.append("discriminator")
            i += 1
            # After discriminator, might have more discriminators (nested) or fields
            # Check if the selected model has nested unions
            selected_model = metadata.discriminator_to_model[element]
            # For now, assume next elements are either more discriminators or fields
            continue

        # Otherwise, it's a field name
        structural.append("field")
        i += 1

    return tuple(structural)


def get_item_index(loc: tuple[str | int, ...]) -> int | None:
    """Extract the top-level list index from an error location, if present.

    Args:
        loc: The location tuple from a Pydantic validation error

    Returns:
        The list index if the error is within a list item, otherwise None
    """
    if loc and isinstance(loc[0], int):
        return loc[0]
    return None


def infer_model_from_error(
    error: dict[str, Any],
    metadata: UnionMetadata,
) -> type[BaseModel] | None:
    """Infer the model type that an error is associated with.

    Uses the LAST (most specific) discriminator or model name found in the
    error path, as nested unions may have multiple discriminators.

    Args:
        error: Pydantic validation error dict
        metadata: Pre-computed UnionMetadata from introspect_union()

    Returns:
        The inferred model type, or None if it cannot be determined
    """
    loc = error["loc"]
    try:
        structural = create_structural_tuple(loc, metadata)

        # Look for discriminator value or model name in the location path
        # Use the LAST one found (most specific) rather than the first
        inferred_model = None
        for element, struct_type in zip(loc, structural, strict=False):
            if struct_type == "discriminator" and isinstance(element, str):
                model = metadata.discriminator_to_model.get(element)
                if model is not None:
                    inferred_model = model
            elif struct_type == "model" and isinstance(element, str):
                model = metadata.model_name_to_model.get(element)
                if model is not None:
                    inferred_model = model

        return inferred_model
    except Exception:
        pass

    return None


def extract_discriminator_path(
    loc: tuple[str | int, ...],
    structural: tuple[StructuralElement, ...],
) -> tuple[str | int, ...]:
    """Extract the discriminator path from a location tuple.

    The discriminator path includes union markers, model names, and discriminator
    values - everything up to (but not including) the first field. List indices are
    excluded to prevent false ambiguity when validating lists of features.

    Args:
        loc: The location tuple from a Pydantic validation error
        structural: The parallel structural tuple

    Returns:
        The discriminator path portion of the location tuple (excluding list_index)
    """
    discriminator_path = []
    for element, struct_type in zip(loc, structural, strict=False):
        if struct_type == "field":
            # Stop at the first field
            break
        if struct_type != "list_index":
            # Include everything except list indices
            discriminator_path.append(element)
    return tuple(discriminator_path)
