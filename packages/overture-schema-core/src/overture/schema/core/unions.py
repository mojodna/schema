"""Utilities for creating union types from Pydantic models."""

from functools import reduce
from operator import or_
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BaseModel, Field


def create_union_from_models(
    models: list[type[BaseModel]],
) -> Any:  # noqa: ANN401
    """Create a union type from models, handling discriminated and non-discriminated models.

    Args:
        models: List of Pydantic model classes

    Returns:
        Union type suitable for parse_feature, properly handling models with and without
        discriminator fields
    """
    if not models:
        raise ValueError("No models provided to create union type")

    if TYPE_CHECKING:
        # For type checking, use Any to avoid mypy errors with dynamic types
        return Any
    else:
        # Filter out BaseModel types without a 'type' field; they can't be discriminated
        # This is an Overture-specific optimization, as our core models all have 'type'
        discriminated_models = []
        non_discriminated_models = []

        for model in models:
            if (
                isinstance(model, type)
                and issubclass(model, BaseModel)
                and "type" not in model.model_fields
            ):
                non_discriminated_models.append(model)
            else:
                # Include union types and models with 'type' field
                discriminated_models.append(model)

        assert discriminated_models or non_discriminated_models

        discriminated_union = None
        if discriminated_models:
            discriminated_union = Annotated[
                reduce(or_, discriminated_models), Field(discriminator="type")
            ]

        non_discriminated_union = reduce(or_, non_discriminated_models, None)

        if discriminated_union and non_discriminated_union:
            model_union = discriminated_union | non_discriminated_union
        elif discriminated_union:
            model_union = discriminated_union
        else:
            model_union = non_discriminated_union

        return model_union
