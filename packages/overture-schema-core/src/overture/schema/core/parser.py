from types import UnionType
from typing import Any, cast

from pydantic import BaseModel

from ._cache import get_type_adapter


def _flatten_feature(feature: dict[str, Any]) -> dict[str, Any]:
    """Flatten a GeoJSON feature to flat/Parquet format.

    Args:
        feature: Feature data (GeoJSON or flattened format)

    Returns:
        Feature in flattened format

    Raises:
        ValueError: If feature is not a dict
    """
    if not isinstance(feature, dict):
        raise ValueError("Feature must be an object")

    # Detect format and normalize to flattened structure
    if "properties" in feature and feature.get("type") == "Feature":
        # GeoJSON format - flatten it
        flattened = {**feature["properties"]}  # Start with properties

        # Add id and geometry if present (let validation catch missing fields)
        if "id" in feature:
            flattened["id"] = feature["id"]
        if "geometry" in feature:
            flattened["geometry"] = feature["geometry"]

        return flattened
    else:
        # Already flattened format
        return feature.copy()


def validate_feature(
    feature: dict[str, Any],
    model_type: type[BaseModel] | UnionType | type,
) -> BaseModel:
    """Validate a feature and return the Pydantic model instance.

    Args:
        feature: Feature data (GeoJSON or flattened format)
        model_type: Pydantic model type or union type to validate against

    Returns:
        Validated Pydantic model instance

    Raises:
        ValidationError: If validation fails
        ValueError: If feature structure is invalid

    Supports both GeoJSON format (with nested properties) and flattened format.
    """
    flattened_feature = _flatten_feature(feature)
    adapter = get_type_adapter(model_type)
    return cast(BaseModel, adapter.validate_python(flattened_feature))


def validate_features(
    features: list[dict[str, Any]],
    model_type: type[BaseModel] | UnionType | type,
) -> list[BaseModel]:
    """Validate a list of features and return Pydantic model instances.

    Args:
        features: List of feature data (GeoJSON or flattened format)
        model_type: Pydantic model type or union type to validate against

    Returns:
        List of validated Pydantic model instances

    Raises:
        ValidationError: If validation fails for any feature
        ValueError: If feature structure is invalid

    Supports both GeoJSON format (with nested properties) and flattened format.
    Each feature in the list is flattened individually before validation.
    """
    flattened_features = [_flatten_feature(f) for f in features]
    list_adapter: Any = get_type_adapter(list[model_type])  # type: ignore[arg-type,valid-type]
    return cast(list[BaseModel], list_adapter.validate_python(flattened_features))


def parse_feature(
    feature: dict[str, Any],
    model_type: type[BaseModel] | UnionType | type,
    mode: str = "json",
) -> dict[str, Any] | None:
    """Parse and validate a feature using the provided model type.

    Args:
        feature: Feature data (GeoJSON or flattened format)
        model_type: Pydantic model type or union type to validate against
        mode: Output mode - "json" for GeoJSON format, "python" for flattened format

    Returns:
        Parsed feature in the specified format

    Supports both GeoJSON format (with nested properties) and flattened format.
    """
    parsed_model = validate_feature(feature, model_type)

    # Return using the requested mode
    return cast(
        dict[str, Any],
        parsed_model.model_dump(exclude_unset=True, mode=mode, by_alias=True),
    )


def parse_features(
    features: list[dict[str, Any]],
    model_type: type[BaseModel] | UnionType | type,
    mode: str = "json",
) -> list[dict[str, Any]]:
    """Parse and validate a list of features using the provided model type.

    Args:
        features: List of feature data (GeoJSON or flattened format)
        model_type: Pydantic model type or union type to validate against
        mode: Output mode - "json" for GeoJSON format, "python" for flattened format

    Returns:
        List of parsed features in the specified format

    Supports both GeoJSON format (with nested properties) and flattened format.
    Each feature in the list is processed individually.
    """
    parsed_models = validate_features(features, model_type)

    # Return using the requested mode
    return [
        model.model_dump(exclude_unset=True, mode=mode, by_alias=True)
        for model in parsed_models
    ]
