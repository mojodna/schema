"""Filter method generation utilities for discriminated unions."""

from pydantic import BaseModel

from .scala_utils import get_discriminator_value


def generate_flattened_filter_methods(
    flattened_name: str, discriminator: str, variants: list[type[BaseModel]]
) -> str:
    """Generate filter methods for each variant in flattened approach."""
    methods = []
    for variant in variants:
        discriminator_value = get_discriminator_value(variant, discriminator)
        method = f"""  def filter{variant.__name__}s(ds: Dataset[{flattened_name}]): Dataset[{flattened_name}] = {{
    ds.filter(col("{discriminator}") === "{discriminator_value}")
  }}"""
        methods.append(method)

    return "\n\n".join(methods)


def generate_filter_methods(
    trait_name: str, discriminator: str, variants: list[type[BaseModel]]
) -> str:
    """Generate type-safe filter methods for each variant."""
    methods = []
    for variant in variants:
        discriminator_value = get_discriminator_value(variant, discriminator)
        method = f"""  def filter{variant.__name__}s(ds: Dataset[{trait_name}]): Dataset[{variant.__name__}] = {{
    ds.filter(col("{discriminator}") === "{discriminator_value}")
      .map(_.asInstanceOf[{variant.__name__}])
  }}"""
        methods.append(method)

    return "\n\n".join(methods)


def generate_simple_filter_methods_with_casting(
    flattened_name: str, discriminator: str, variants: list
) -> str:
    """Generate filter methods that return narrowed types using .as[] casting."""
    methods = []
    for variant in variants:
        discriminator_value = get_discriminator_value(variant, discriminator)
        method = f"""  def filter{variant.__name__}s(ds: Dataset[{flattened_name}]): Dataset[{variant.__name__}] = {{
    ds.filter(col("{discriminator}") === "{discriminator_value}").as[{variant.__name__}]
  }}"""
        methods.append(method)

    return "\n\n".join(methods)
