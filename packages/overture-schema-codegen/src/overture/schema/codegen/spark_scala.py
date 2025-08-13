"""Spark-compatible Scala code generator from Pydantic models."""

import inspect
from typing import Any

from pydantic import BaseModel

from .case_class_generation import generate_spark_case_class_with_nested
from .discriminated_union import generate_spark_discriminated_union
from .introspection import is_discriminated_union
from .spark_validation_generator import SparkValidationCodeGenerator


def generate_spark_scala_code(
    model_class: type[BaseModel] | Any,
    package: str | None = None,
    with_validation: bool = False,
) -> str:
    """Generate Spark-compatible Scala code from Pydantic model or discriminated union."""

    # Check if it's a discriminated union
    is_union, discriminator, variants = is_discriminated_union(model_class)

    if is_union and variants:
        return generate_spark_discriminated_union(
            model_class, discriminator, variants, package
        )
    elif inspect.isclass(model_class) and issubclass(model_class, BaseModel):
        base_code = generate_spark_case_class_with_nested(model_class, package)

        if with_validation:
            # Add validation methods to the companion object
            from .spark_validation_generator import SparkValidationCodeGenerator

            validation_generator = SparkValidationCodeGenerator(package)

            # Generate ValidationError case class (top-level)
            validation_error_class = (
                validation_generator.generate_validation_error_case_class()
            )

            # Generate validation methods for companion object
            validation_methods = (
                validation_generator.generate_companion_validation_methods(
                    model_class, model_class.__name__
                )
            )

            # Insert ValidationError before case class and validation methods before companion object closing
            if "case class " in base_code and "}\n" in base_code:
                # Add ValidationError case class before the main case class
                case_class_start = base_code.find("case class ")
                before_case_class = base_code[:case_class_start]
                after_case_class = base_code[case_class_start:]

                base_code = (
                    before_case_class
                    + validation_error_class
                    + "\n\n"
                    + after_case_class
                )

                # Add validation methods to companion object
                parts = base_code.rsplit("}", 1)
                if len(parts) == 2:
                    base_code = parts[0] + validation_methods + "\n}\n" + parts[1]

        return base_code
    else:
        raise ValueError(f"Cannot generate Spark Scala code for: {model_class}")


def generate_spark_validation_code(
    model_class: type[BaseModel],
    package: str | None = None,
    model_name: str | None = None,
) -> tuple[str, str]:
    """Generate Spark validation code for Pydantic models.

    Returns:
        tuple: (validator_library_code, batch_validator_code)
    """
    generator = SparkValidationCodeGenerator(package=package)

    if model_name is None:
        model_name = model_class.__name__

    validator_library = generator.generate_validation_library(model_class, model_name)
    batch_validator = generator.generate_batch_validator(model_class, model_name)

    return validator_library, batch_validator
