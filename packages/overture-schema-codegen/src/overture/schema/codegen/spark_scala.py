"""Spark-compatible Scala code generator from Pydantic models."""

import inspect
from typing import Any

from pydantic import BaseModel

from .case_class_generation import generate_spark_case_class_with_nested
from .discriminated_union import generate_spark_discriminated_union
from .introspection import is_discriminated_union


def generate_spark_scala_code(
    model_class: type[BaseModel] | Any, package: str | None = None
) -> str:
    """Generate Spark-compatible Scala code from Pydantic model or discriminated union."""

    # Check if it's a discriminated union
    is_union, discriminator, variants = is_discriminated_union(model_class)

    if is_union and variants:
        return generate_spark_discriminated_union(
            model_class, discriminator, variants, package
        )
    elif inspect.isclass(model_class) and issubclass(model_class, BaseModel):
        return generate_spark_case_class_with_nested(model_class, package)
    else:
        raise ValueError(f"Cannot generate Spark Scala code for: {model_class}")
