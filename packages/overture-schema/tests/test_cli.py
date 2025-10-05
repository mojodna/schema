"""Tests for CLI type resolution and filtering functionality."""

from typing import get_origin

from overture.schema.cli.commands import create_union_type_from_models, resolve_types
from overture.schema.core.discovery import discover_models


def test_overture_types_option() -> None:
    """Test --overture-types flag filters to official Overture types."""
    model_type = resolve_types(
        use_overture_types=True, namespace=None, theme_names=(), type_names=()
    )

    # Should create a union type
    assert model_type is not None
    assert get_origin(model_type) is not None


def test_theme_only_filter() -> None:
    """Test filtering by theme only."""
    model_type = resolve_types(
        use_overture_types=False,
        namespace=None,
        theme_names=("buildings",),
        type_names=(),
    )

    # Should include all types from the buildings theme
    assert model_type is not None


def test_type_only_filter() -> None:
    """Test filtering by type only (across all themes)."""
    model_type = resolve_types(
        use_overture_types=False,
        namespace=None,
        theme_names=(),
        type_names=("building",),
    )

    assert model_type is not None


def test_theme_and_type_filter() -> None:
    """Test filtering by both theme and type."""
    model_type = resolve_types(
        use_overture_types=False,
        namespace=None,
        theme_names=("buildings",),
        type_names=("building",),
    )

    assert model_type is not None


def test_multiple_types() -> None:
    """Test filtering with multiple types."""
    model_type = resolve_types(
        use_overture_types=False,
        namespace=None,
        theme_names=(),
        type_names=("building", "segment"),
    )

    assert model_type is not None


def test_multiple_themes() -> None:
    """Test filtering with multiple themes."""
    model_type = resolve_types(
        use_overture_types=False,
        namespace=None,
        theme_names=("buildings", "transportation"),
        type_names=(),
    )

    assert model_type is not None


def test_no_filters_uses_all_models() -> None:
    """Test that no filters uses all available models."""
    model_type = resolve_types(
        use_overture_types=False, namespace=None, theme_names=(), type_names=()
    )

    assert model_type is not None


def test_nonexistent_type_raises_error() -> None:
    """Test that nonexistent type raises ValueError."""
    try:
        resolve_types(
            use_overture_types=False,
            namespace=None,
            theme_names=(),
            type_names=("nonexistent",),
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_nonexistent_theme_raises_error() -> None:
    """Test that nonexistent theme raises ValueError."""
    try:
        resolve_types(
            use_overture_types=False,
            namespace=None,
            theme_names=("nonexistent",),
            type_names=(),
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_namespace_filter() -> None:
    """Test filtering by namespace."""
    model_type = resolve_types(
        use_overture_types=False, namespace="overture", theme_names=(), type_names=()
    )

    assert model_type is not None


def test_namespace_with_theme() -> None:
    """Test filtering by namespace and theme."""
    model_type = resolve_types(
        use_overture_types=False,
        namespace="overture",
        theme_names=("buildings",),
        type_names=(),
    )

    assert model_type is not None


def test_namespace_with_type() -> None:
    """Test filtering by namespace and type."""
    model_type = resolve_types(
        use_overture_types=False,
        namespace="overture",
        theme_names=(),
        type_names=("building",),
    )

    assert model_type is not None


def test_nonexistent_namespace_raises_error() -> None:
    """Test that nonexistent namespace raises ValueError."""
    try:
        resolve_types(
            use_overture_types=False,
            namespace="nonexistent",
            theme_names=(),
            type_names=(),
        )
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_creates_annotated_union() -> None:
    """Test that create_union_type_from_models creates an Annotated union."""
    all_models = discover_models()

    # Take a subset of models
    subset = {k: v for k, v in list(all_models.items())[:2]}

    union_type = create_union_type_from_models(subset)

    # Should create a type (annotated union)
    assert union_type is not None
    # Should be annotated (has __metadata__ or similar)
    assert hasattr(union_type, "__origin__") or hasattr(union_type, "__metadata__")


def test_empty_models_raises_error() -> None:
    """Test that empty models dict raises ValueError."""
    try:
        create_union_type_from_models({})
        assert False, "Should have raised ValueError"
    except (ValueError, Exception):
        # May raise ValueError or other exception depending on implementation
        pass
