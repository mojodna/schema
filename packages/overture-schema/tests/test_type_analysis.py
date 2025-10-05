"""Tests for type analysis and structural tuple functionality."""

from typing import Annotated, Literal

from overture.schema.cli.type_analysis import create_structural_tuple, introspect_union
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
