"""Pydantic model introspection utilities for code generation."""

import enum
import inspect
import types
from dataclasses import dataclass
from typing import Annotated, Any, Optional, Union, get_args, get_origin

from pydantic import BaseModel, Field


@dataclass
class FieldInfo:
    """Information about a Pydantic model field."""

    name: str
    python_type: type
    annotation: Any
    is_required: bool
    is_nullable: bool
    default_value: Any
    description: str | None
    alias: str | None = None  # Pydantic field alias for serialization/schema
    nested_model: type[BaseModel] | None = None
    is_discriminated_union: bool = False
    discriminator_field: str | None = None
    union_variants: list[type[BaseModel]] | None = None


def is_discriminated_union(
    annotation: Any,
) -> tuple[bool, str | None, list[type[BaseModel]] | None]:
    """Check if an annotation is a discriminated union and extract its info.

    Returns:
        Tuple of (is_discriminated_union, discriminator_field, variant_models)
    """
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        if len(args) >= 2:
            actual_type = args[0]
            metadata = args[1:]

            # Look for Field(discriminator="field_name") in metadata
            for item in metadata:
                try:
                    if hasattr(item, "discriminator") and item.discriminator:
                        # Check if the actual type is a Union
                        union_origin = get_origin(actual_type)
                        if union_origin is Union or isinstance(
                            actual_type, types.UnionType
                        ):
                            union_args = (
                                get_args(actual_type)
                                if union_origin is Union
                                else actual_type.__args__
                            )

                            # Extract BaseModel variants
                            variants = []
                            for variant in union_args:
                                if inspect.isclass(variant) and issubclass(
                                    variant, BaseModel
                                ):
                                    variants.append(variant)

                            if variants:
                                return True, item.discriminator, variants
                except (TypeError, AttributeError):
                    continue

    return False, None, None


def extract_discriminated_union_info(annotation: Any) -> dict[str, Any]:
    """Extract comprehensive information about a discriminated union."""
    is_union, discriminator, variants = is_discriminated_union(annotation)

    if not is_union:
        return {}

    return {
        "is_discriminated_union": True,
        "discriminator_field": discriminator,
        "variants": [
            {
                "name": variant.__name__,
                "model": variant,
                "fields": list(variant.model_fields.keys()),
            }
            for variant in variants
        ],
    }


def extract_fields_recursive(
    model_class_or_union: type[BaseModel] | Any,
) -> list[FieldInfo]:
    """Extract all fields from a Pydantic model or discriminated union recursively.

    Args:
        model_class_or_union: Either a Pydantic BaseModel class or a discriminated union

    Returns:
        List of FieldInfo objects describing all fields in the model and nested models
    """
    # Check if it's a discriminated union first
    is_union, discriminator, variants = is_discriminated_union(model_class_or_union)

    if is_union:
        # Handle discriminated union by processing all variants
        fields = []
        processed_models = set()

        # Create a summary field for the union itself
        union_field = FieldInfo(
            name="<discriminated_union>",
            python_type=type(model_class_or_union),
            annotation=model_class_or_union,
            is_required=True,
            is_nullable=False,
            default_value=None,
            description=f"Discriminated union with {len(variants)} variants",
            is_discriminated_union=True,
            discriminator_field=discriminator,
            union_variants=variants,
        )
        fields.append(union_field)

        # Process each variant
        for variant in variants:
            variant_fields = extract_fields_recursive(variant)
            # Prefix variant fields with variant name
            for field in variant_fields:
                field.name = f"{variant.__name__}.{field.name}"
            fields.extend(variant_fields)

        return fields

    # Handle regular BaseModel
    if not (
        inspect.isclass(model_class_or_union)
        and issubclass(model_class_or_union, BaseModel)
    ):
        raise ValueError(
            f"Expected a Pydantic BaseModel class or discriminated union, got {model_class_or_union}"
        )

    fields = []
    processed_models = set()

    def _extract_fields_from_model(model: type[BaseModel], prefix: str = "") -> None:
        """Extract fields from a model, tracking processed models to avoid infinite recursion."""
        model_id = id(model)
        if model_id in processed_models:
            return
        processed_models.add(model_id)

        for field_name, field_info in model.model_fields.items():
            # Use alias if available, otherwise use field name
            display_name = getattr(field_info, "alias", None) or field_name
            full_field_name = f"{prefix}{display_name}" if prefix else display_name

            field_data = FieldInfo(
                name=full_field_name,
                python_type=_get_base_type(field_info.annotation),
                annotation=field_info.annotation,
                is_required=field_info.is_required(),
                is_nullable=_is_nullable(field_info.annotation),
                default_value=field_info.default
                if hasattr(field_info, "default")
                else None,
                description=field_info.description,
                alias=getattr(field_info, "alias", None),
            )

            # Check if this field contains a nested Pydantic model
            nested_model = _extract_nested_model(field_info.annotation)
            if nested_model:
                field_data.nested_model = nested_model

            # Add the parent field first
            fields.append(field_data)

            # Then immediately process nested fields if any
            if nested_model:
                _extract_fields_from_model(nested_model, f"{full_field_name}.")

    _extract_fields_from_model(model_class_or_union)
    return fields


def _get_base_type(annotation: Any) -> type:
    """Extract the base type from a potentially complex type annotation."""
    # Handle new union syntax (Python 3.10+)
    if isinstance(annotation, types.UnionType):
        args = annotation.__args__
        if len(args) == 2 and type(None) in args:
            return args[0] if args[1] is type(None) else args[1]
        # For other unions, return the first non-None type
        return next((arg for arg in args if arg is not type(None)), args[0])

    origin = get_origin(annotation)

    if origin is Union:
        # Handle Optional types (Union[X, None])
        args = get_args(annotation)
        if len(args) == 2 and type(None) in args:
            return args[0] if args[1] is type(None) else args[1]
        # For other unions, return the first non-None type
        return next((arg for arg in args if arg is not type(None)), args[0])

    if origin is not None:
        # For generic types like List[str], Dict[str, int], etc.
        return origin

    return annotation


def _is_nullable(annotation: Any) -> bool:
    """Check if a type annotation represents a nullable field."""
    # Handle new union syntax (Python 3.10+)
    if isinstance(annotation, types.UnionType):
        return type(None) in annotation.__args__

    origin = get_origin(annotation)

    if origin is Union:
        args = get_args(annotation)
        return type(None) in args

    return False


def _extract_nested_model(annotation: Any) -> type[BaseModel] | None:
    """Extract nested Pydantic model from type annotation if present."""
    # Handle direct BaseModel reference
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation

    # Handle NewType wrappers
    if hasattr(annotation, "__supertype__"):
        underlying_type = annotation.__supertype__
        return _extract_nested_model(underlying_type)

    # Handle Annotated types
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            return _extract_nested_model(actual_type)

    # Handle new union syntax (Python 3.10+)
    if isinstance(annotation, types.UnionType):
        for arg in annotation.__args__:
            if (
                arg is not type(None)
                and inspect.isclass(arg)
                and issubclass(arg, BaseModel)
            ):
                return arg

    # Handle Optional[BaseModel] or Union[BaseModel, None]
    if origin is Union:
        args = get_args(annotation)
        for arg in args:
            if (
                arg is not type(None)
                and inspect.isclass(arg)
                and issubclass(arg, BaseModel)
            ):
                return arg

    # Handle List[BaseModel], Dict[str, BaseModel], etc.
    if origin is not None:
        args = get_args(annotation)
        for arg in args:
            nested = _extract_nested_model(arg)
            if nested:
                return nested

    return None


def get_model_hierarchy(model_class: type[BaseModel]) -> dict[str, Any]:
    """Get a hierarchical representation of the model structure.

    Args:
        model_class: The Pydantic BaseModel class to analyze

    Returns:
        Dictionary representing the model hierarchy with nested structures
    """
    if not (inspect.isclass(model_class) and issubclass(model_class, BaseModel)):
        raise ValueError(f"Expected a Pydantic BaseModel class, got {model_class}")

    def _build_hierarchy(model: type[BaseModel]) -> dict[str, Any]:
        hierarchy = {"name": model.__name__, "fields": {}, "nested_models": {}}

        for field_name, field_info in model.model_fields.items():
            field_data = {
                "type": str(field_info.annotation),
                "required": field_info.is_required(),
                "nullable": _is_nullable(field_info.annotation),
                "description": field_info.description,
            }

            nested_model = _extract_nested_model(field_info.annotation)
            if nested_model:
                field_data["nested_model"] = nested_model.__name__
                hierarchy["nested_models"][nested_model.__name__] = _build_hierarchy(
                    nested_model
                )

            hierarchy["fields"][field_name] = field_data

        return hierarchy

    return _build_hierarchy(model_class)


def collect_all_basemodel_types(
    model_class_or_union: type[BaseModel] | Any,
) -> set[type[BaseModel]]:
    """Collect all BaseModel types encountered during traversal of a model or union.

    Args:
        model_class_or_union: Either a Pydantic BaseModel class or a discriminated union

    Returns:
        Set of unique BaseModel types found during traversal

    TODO: Also collect and serialize enums, type aliases, and NewType definitions
    encountered during traversal to provide complete MDX documentation for all
    referenced types. This would require extending the collection logic and
    creating serialization methods for these type constructs.
    """
    collected_types = set()

    def _collect_from_model(model: type[BaseModel]) -> None:
        """Recursively collect BaseModel types from a model."""
        if not (inspect.isclass(model) and issubclass(model, BaseModel)):
            return

        # Add the model itself
        collected_types.add(model)

        # Process all fields to find nested models
        for field_name, field_info in model.model_fields.items():
            nested_models = _extract_all_nested_models(field_info.annotation)
            for nested_model in nested_models:
                if nested_model not in collected_types:
                    _collect_from_model(nested_model)

    # Check if it's a discriminated union first
    is_union, discriminator, variants = is_discriminated_union(model_class_or_union)

    if is_union and variants:
        # For unions, collect from all variants
        for variant in variants:
            _collect_from_model(variant)
    else:
        # For regular models
        _collect_from_model(model_class_or_union)

    return collected_types


def collect_all_enum_types(
    model_class_or_union: type[BaseModel] | Any,
) -> set[type[enum.Enum]]:
    """Collect all Enum types encountered during traversal of a model or union.

    Args:
        model_class_or_union: Either a Pydantic BaseModel class or a discriminated union

    Returns:
        Set of unique Enum types found during traversal
    """
    collected_enums = set()

    def _collect_enums_from_model(model: type[BaseModel]) -> None:
        """Recursively collect Enum types from a model."""
        if not (inspect.isclass(model) and issubclass(model, BaseModel)):
            return

        # Process all fields to find enums
        for field_name, field_info in model.model_fields.items():
            enums_in_field = _extract_all_enums(field_info.annotation)
            collected_enums.update(enums_in_field)

            # Also collect from nested BaseModels
            nested_models = _extract_all_nested_models(field_info.annotation)
            for nested_model in nested_models:
                _collect_enums_from_model(nested_model)

    # Check if it's a discriminated union first
    is_union, discriminator, variants = is_discriminated_union(model_class_or_union)

    if is_union and variants:
        # For unions, collect from all variants
        for variant in variants:
            _collect_enums_from_model(variant)
    else:
        # For regular models
        _collect_enums_from_model(model_class_or_union)

    return collected_enums


def _extract_all_enums(annotation: Any) -> list[type[enum.Enum]]:
    """Extract all Enum types from a type annotation."""
    enums = []

    # Handle direct Enum reference
    if inspect.isclass(annotation) and issubclass(annotation, enum.Enum):
        enums.append(annotation)
        return enums

    # Handle NewType wrappers
    if hasattr(annotation, "__supertype__"):
        underlying_type = annotation.__supertype__
        enums.extend(_extract_all_enums(underlying_type))
        return enums

    # Handle Annotated types
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            enums.extend(_extract_all_enums(actual_type))
            return enums

    # Handle new union syntax (Python 3.10+)
    if isinstance(annotation, types.UnionType):
        for arg in annotation.__args__:
            if arg is not type(None):
                enums.extend(_extract_all_enums(arg))
        return enums

    # Handle Union types
    if origin is Union:
        args = get_args(annotation)
        for arg in args:
            if arg is not type(None):
                enums.extend(_extract_all_enums(arg))
        return enums

    # Handle generic types like List[Enum], Dict[str, Enum], etc.
    if origin is not None:
        args = get_args(annotation)
        for arg in args:
            enums.extend(_extract_all_enums(arg))
        return enums

    return enums


def _extract_all_nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Extract all nested Pydantic models from a type annotation."""
    models = []

    # Handle direct BaseModel reference
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        models.append(annotation)
        return models

    # Handle NewType wrappers
    if hasattr(annotation, "__supertype__"):
        underlying_type = annotation.__supertype__
        models.extend(_extract_all_nested_models(underlying_type))
        return models

    # Handle Annotated types
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            # The first argument is the actual type
            actual_type = args[0]
            models.extend(_extract_all_nested_models(actual_type))
            return models

    # Handle new union syntax (Python 3.10+)
    if isinstance(annotation, types.UnionType):
        for arg in annotation.__args__:
            if arg is not type(None):
                models.extend(_extract_all_nested_models(arg))
        return models

    # Handle Union types
    if origin is Union:
        args = get_args(annotation)
        for arg in args:
            if arg is not type(None):
                models.extend(_extract_all_nested_models(arg))
        return models

    # Handle generic types like List[BaseModel], Dict[str, BaseModel], etc.
    if origin is not None:
        args = get_args(annotation)
        for arg in args:
            models.extend(_extract_all_nested_models(arg))
        return models

    return models
