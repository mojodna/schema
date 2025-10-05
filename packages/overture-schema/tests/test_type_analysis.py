"""Tests for type analysis and structural tuple functionality."""

from typing import Annotated, Literal

import pytest
from overture.schema.cli.type_analysis import (
    create_structural_tuple,
    extract_discriminator_path,
    introspect_union,
)
from pydantic import BaseModel, Field


class TestStructuralTuples:
    """Tests for creating structural tuples from error loc paths."""

    def test_simple_discriminated_union_structural_tuple(self) -> None:
        """Test structural tuple for simple discriminated union errors."""

        class ModelA(BaseModel):
            type: Literal["a"]
            required_a: int

        class ModelB(BaseModel):
            type: Literal["b"]
            required_b: int

        UnionType = Annotated[ModelA | ModelB, Field(discriminator="type")]

        # Test simple discriminated union error path
        loc = ("a", "required_a")
        metadata = introspect_union(UnionType)
        structural = create_structural_tuple(loc, metadata)
        print(f"\nloc: {loc}")
        print(f"structural: {structural}")
        assert len(structural) == len(loc)
        # First element should be discriminator, second should be field
        assert structural == ("discriminator", "field")

    def test_mixed_union_structural_tuple(self) -> None:
        """Test structural tuple for mixed discriminated/non-discriminated union."""

        class ModelA(BaseModel):
            type: Literal["a"]
            required_a: int

        class Sources(BaseModel):
            datasets: list[str]

        DiscriminatedUnion = Annotated[ModelA, Field(discriminator="type")]
        MixedUnion = DiscriminatedUnion | Sources
        metadata = introspect_union(MixedUnion)

        # Test discriminated side
        loc1 = ("tagged-union[ModelA]", "a", "required_a")
        structural1 = create_structural_tuple(loc1, metadata)
        print("\nDiscriminated side:")
        print(f"loc: {loc1}")
        print(f"structural: {structural1}")
        assert structural1 == ("union", "discriminator", "field")

        # Test non-discriminated side
        loc2 = ("Sources", "datasets")
        structural2 = create_structural_tuple(loc2, metadata)
        print("\nNon-discriminated side:")
        print(f"loc: {loc2}")
        print(f"structural: {structural2}")
        assert structural2 == ("model", "field")

    def test_list_context_structural_tuple(self) -> None:
        """Test structural tuple for union in list context."""

        class ModelA(BaseModel):
            type: Literal["a"]
            required_a: int

        UnionType = Annotated[ModelA, Field(discriminator="type")]

        # Test list context
        loc = (1, "a", "required_a")
        metadata = introspect_union(list[UnionType])
        structural = create_structural_tuple(loc, metadata)
        print("\nList context:")
        print(f"loc: {loc}")
        print(f"structural: {structural}")
        assert structural == ("list_index", "discriminator", "field")

    def test_nested_discriminated_structural_tuple(self) -> None:
        """Test structural tuple for nested discriminated unions."""

        class Building(BaseModel):
            type: Literal["building"]
            height: float

        class RoadSegment(BaseModel):
            type: Literal["segment"]
            subtype: Literal["road"]
            road_class: str

        class RailSegment(BaseModel):
            type: Literal["segment"]
            subtype: Literal["rail"]
            rail_class: str

        class Sources(BaseModel):
            datasets: list[str]

        # Create nested discriminated unions
        SegmentUnion = Annotated[
            RoadSegment | RailSegment, Field(discriminator="subtype")
        ]
        FeatureUnion = Annotated[Building | SegmentUnion, Field(discriminator="type")]
        MixedUnion = FeatureUnion | Sources

        # Test nested discriminator path (type=segment, subtype=road)
        loc = ("tagged-union[SegmentUnion]", "segment", "road", "road_class")
        metadata = introspect_union(MixedUnion)
        structural = create_structural_tuple(loc, metadata)
        print("\nNested discriminated:")
        print(f"loc: {loc}")
        print(f"structural: {structural}")
        assert structural == ("union", "discriminator", "discriminator", "field")


class TestExtractDiscriminatorPath:
    """Tests for extract_discriminator_path function."""

    @pytest.mark.parametrize(
        "loc,structural,expected_path",
        [
            # Simple cases
            pytest.param(
                ("a", "field_name"),
                ("discriminator", "field"),
                ("a",),
                id="simple_discriminator",
            ),
            pytest.param(
                ("ModelA", "field_name"),
                ("model", "field"),
                ("ModelA",),
                id="simple_model",
            ),
            pytest.param(
                ("field_name",),
                ("field",),
                (),
                id="no_discriminator",
            ),
            # With list indices (should be excluded)
            pytest.param(
                (0, "a", "field_name"),
                ("list_index", "discriminator", "field"),
                ("a",),
                id="list_then_discriminator",
            ),
            pytest.param(
                (0, 1, "a", "field_name"),
                ("list_index", "list_index", "discriminator", "field"),
                ("a",),
                id="nested_list_then_discriminator",
            ),
            # Union markers
            pytest.param(
                ("tagged-union[A]", "a", "field_name"),
                ("union", "discriminator", "field"),
                ("tagged-union[A]", "a"),
                id="union_with_discriminator",
            ),
            # Nested discriminators
            pytest.param(
                ("tagged-union[A]", "a", "b", "field_name"),
                ("union", "discriminator", "discriminator", "field"),
                ("tagged-union[A]", "a", "b"),
                id="nested_discriminators",
            ),
            # Complex case with list, union, and multiple discriminators
            pytest.param(
                (0, "tagged-union[A]", "a", "b", "field_name"),
                ("list_index", "union", "discriminator", "discriminator", "field"),
                ("tagged-union[A]", "a", "b"),
                id="complex_with_list_union_nested",
            ),
        ],
    )
    def test_extract_discriminator_path_variations(
        self,
        loc: tuple[str | int, ...],
        structural: tuple[str, ...],
        expected_path: tuple[str | int, ...],
    ) -> None:
        """Test extract_discriminator_path with various input patterns."""
        result = extract_discriminator_path(loc, structural)
        assert result == expected_path


class TestIntrospectUnion:
    """Tests for introspect_union function."""

    def test_introspect_simple_discriminated_union(self) -> None:
        """Test introspection of a simple discriminated union."""

        class ModelA(BaseModel):
            type: Literal["a"]
            value: int

        class ModelB(BaseModel):
            type: Literal["b"]
            value: str

        UnionType = Annotated[ModelA | ModelB, Field(discriminator="type")]
        metadata = introspect_union(UnionType)

        assert metadata.is_discriminated is True
        assert metadata.discriminator_field == "type"
        assert "a" in metadata.discriminator_to_model
        assert "b" in metadata.discriminator_to_model
        assert metadata.discriminator_to_model["a"] == ModelA
        assert metadata.discriminator_to_model["b"] == ModelB

    def test_introspect_non_discriminated_union(self) -> None:
        """Test introspection of a non-discriminated union."""

        class ModelA(BaseModel):
            field_a: int

        class ModelB(BaseModel):
            field_b: str

        UnionType = ModelA | ModelB
        metadata = introspect_union(UnionType)

        assert metadata.is_discriminated is False
        assert metadata.discriminator_field is None
        assert "ModelA" in metadata.model_name_to_model
        assert "ModelB" in metadata.model_name_to_model

    def test_introspect_list_of_union(self) -> None:
        """Test introspection unwraps list types correctly."""

        class ModelA(BaseModel):
            type: Literal["a"]

        UnionType = Annotated[ModelA, Field(discriminator="type")]
        ListType = list[UnionType]

        metadata = introspect_union(ListType)

        # Should unwrap the list and introspect the inner union
        assert metadata.is_discriminated is True
        assert metadata.discriminator_field == "type"
        assert "a" in metadata.discriminator_to_model

    @pytest.mark.parametrize(
        "literal_value,expected_in_mapping",
        [
            pytest.param("building", True, id="literal_building"),
            pytest.param("place", True, id="literal_place"),
            pytest.param("nonexistent", False, id="not_present"),
        ],
    )
    def test_introspect_extracts_all_literals(
        self, literal_value: str, expected_in_mapping: bool
    ) -> None:
        """Test that introspect_union extracts all Literal field values."""

        class Building(BaseModel):
            type: Literal["building"]
            subtype: Literal["residential"]

        class Place(BaseModel):
            type: Literal["place"]
            category: Literal["restaurant"]

        UnionType = Annotated[Building | Place, Field(discriminator="type")]
        metadata = introspect_union(UnionType)

        if expected_in_mapping:
            assert literal_value in metadata.discriminator_to_model
        else:
            assert literal_value not in metadata.discriminator_to_model
