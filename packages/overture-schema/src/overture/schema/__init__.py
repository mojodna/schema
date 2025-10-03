__path__ = __import__("pkgutil").extend_path(__path__, __name__)

from typing import Any

from overture.schema.core import parse_feature
from overture.schema.core.discovery import discover_models
from overture.schema.core.json_schema import json_schema
from overture.schema.core.parser import (
    parse_features,
    validate_feature,
    validate_features,
)
from overture.schema.core.unions import create_union_from_models


def parse(feature: dict[str, Any], mode: str = "json") -> dict[str, Any] | None:
    """Parse and validate a feature using the union of all available models.

    Args:
        feature: Feature data (GeoJSON or flattened format)
        mode: Output mode - "json" for GeoJSON format, "python" for flattened format

    Returns:
        Parsed feature in the specified format

    Uses the discovery mechanism to find all registered models and validates
    the feature against the union of all available models.
    """
    # Discover all registered models via entry points
    models = discover_models()
    if not models:
        raise ValueError("No registered models found via entry points")

    return parse_feature(feature, create_union_from_models(list(models.values())), mode)


__all__ = [
    "parse",
    "parse_feature",
    "parse_features",
    "validate_feature",
    "validate_features",
    "json_schema",
]
