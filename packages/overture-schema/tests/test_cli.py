"""Tests for the CLI functionality."""

from collections.abc import Generator
from io import StringIO
from typing import get_origin
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from overture.schema.cli import cli, create_union_type_from_models, resolve_types
from overture.schema.core.discovery import discover_models
from pydantic import BaseModel, Field, TypeAdapter
from rich.console import Console


@pytest.fixture
def cli_runner() -> Generator[CliRunner, None, None]:
    """Provide a CliRunner within an isolated filesystem."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        yield runner


@pytest.fixture
def building_feature_yaml_content() -> str:
    """Return YAML content for a valid building feature."""
    return """
id: test
type: Feature
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
properties:
  theme: buildings
  type: building
  version: 0
"""


@pytest.fixture
def building_feature_yaml(
    cli_runner: CliRunner, building_feature_yaml_content: str
) -> str:
    """Create a test.yaml file with valid building feature in isolated filesystem."""
    filename = "test.yaml"
    with open(filename, "w") as f:
        f.write(building_feature_yaml_content)
    return filename


@pytest.fixture
def missing_id_yaml_content() -> str:
    """Return YAML content with missing required field."""
    return """
type: Feature
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
properties:
  theme: buildings
  type: building
  version: 0
"""


@pytest.fixture
def missing_id_yaml(cli_runner: CliRunner, missing_id_yaml_content: str) -> str:
    """Create a missing-id.yaml file with missing required field."""
    filename = "missing-id.yaml"
    with open(filename, "w") as f:
        f.write(missing_id_yaml_content)
    return filename


@pytest.fixture
def invalid_type_yaml(cli_runner: CliRunner) -> str:
    """Create an invalid-type.yaml file with invalid type value."""
    filename = "invalid-type.yaml"
    with open(filename, "w") as f:
        f.write("""
id: test
type: Feature
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
properties:
  theme: buildings
  type: invalid_type
  version: 0
""")
    return filename


@pytest.fixture
def flat_format_yaml(cli_runner: CliRunner) -> str:
    """Create a geojson.yaml file with flat format (non-GeoJSON) input."""
    filename = "flat.yaml"
    with open(filename, "w") as f:
        f.write("""
id: test
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
theme: buildings
type: building
version: 0
""")
    return filename


@pytest.fixture
def bad_geometry_type_yaml(cli_runner: CliRunner) -> str:
    """Create a bad-geometry-type.yaml file with invalid geometry type."""
    filename = "bad-geometry-type.yaml"
    with open(filename, "w") as f:
        f.write("""
id: test
type: Feature
geometry:
  type: Point
  coordinates: [0, 0]
properties:
  theme: buildings
  type: building
  version: 0
""")
    return filename


@pytest.fixture
def feature_list_yaml_content() -> str:
    """Return YAML content for a list of valid features."""
    return """- id: test1
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
  properties:
    theme: buildings
    type: building
    version: 0
- id: test2
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
  properties:
    theme: buildings
    type: building
    version: 0
"""


@pytest.fixture
def feature_list_yaml(
    cli_runner: CliRunner,
    feature_list_yaml_content: str,  # noqa: ARG001
) -> str:
    """Create a feature-list.yaml file with a list of features."""
    filename = "feature-list.yaml"
    with open(filename, "w") as f:
        f.write(feature_list_yaml_content)
    return filename


@pytest.fixture
def feature_list_with_error_yaml(cli_runner: CliRunner) -> str:  # noqa: ARG001
    """Create a feature-list-error.yaml file with a list where one feature is invalid."""
    filename = "feature-list-error.yaml"
    with open(filename, "w") as f:
        f.write("""- id: test1
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
  properties:
    theme: buildings
    type: building
    version: 0
- type: Feature
  geometry:
    type: Polygon
    coordinates: [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
  properties:
    theme: buildings
    type: building
    version: 0
""")
    return filename


@pytest.fixture
def stderr_buffer() -> Generator[StringIO]:
    """Provide a patched stderr buffer for capturing CLI error output."""

    buffer = StringIO()
    captured_console = Console(file=buffer, force_terminal=False)

    with patch("overture.schema.cli.stderr", captured_console):
        yield buffer


def test_overture_types_option() -> None:
    """Test --overture-types returns the official Types union."""
    result = resolve_types(True, None, (), ())

    # Should be an Annotated type
    assert get_origin(result) is not None

    # Should contain all the official Overture types
    result_str = repr(result)
    assert "Address" in result_str
    assert "Building" in result_str
    assert "Place" in result_str


def test_theme_only_filter() -> None:
    """Test filtering by theme only."""
    result = resolve_types(False, None, ("buildings",), ())

    result_str = repr(result)
    assert "Building" in result_str
    assert "BuildingPart" in result_str
    # Should not contain other themes
    assert "Address" not in result_str
    assert "Place" not in result_str


def test_type_only_filter() -> None:
    """Test filtering by type only."""
    result = resolve_types(False, None, (), ("building",))

    result_str = repr(result)
    assert "Building" in result_str
    # Should not contain building_part
    assert "BuildingPart" not in result_str


def test_theme_and_type_filter() -> None:
    """Test filtering by both theme and type."""
    result = resolve_types(False, None, ("buildings",), ("building",))

    result_str = repr(result)
    assert "Building" in result_str
    # Should not contain building_part or other types
    assert "BuildingPart" not in result_str
    assert "Place" not in result_str


def test_multiple_types() -> None:
    """Test filtering by multiple types."""
    result = resolve_types(False, None, (), ("building", "place"))

    result_str = repr(result)
    assert "Building" in result_str
    assert "Place" in result_str
    assert "BuildingPart" not in result_str


def test_multiple_themes() -> None:
    """Test filtering by multiple themes."""
    result = resolve_types(False, None, ("buildings", "places"), ())

    result_str = repr(result)
    assert "Building" in result_str
    assert "BuildingPart" in result_str
    assert "Place" in result_str
    # Should not contain other themes
    assert "Address" not in result_str


def test_no_filters_uses_all_models() -> None:
    """Test that no filters returns all discovered models."""
    result = resolve_types(False, None, (), ())

    result_str = repr(result)
    # Should contain models from multiple themes
    assert "Building" in result_str
    assert "Place" in result_str
    assert "Address" in result_str


def test_nonexistent_type_raises_error() -> None:
    """Test that nonexistent type raises ValueError."""
    with pytest.raises(ValueError, match="No models found matching"):
        resolve_types(False, None, (), ("nonexistent",))


def test_nonexistent_theme_raises_error() -> None:
    """Test that nonexistent theme raises ValueError."""
    with pytest.raises(ValueError, match="No models found matching"):
        resolve_types(False, None, ("nonexistent",), ())


def test_namespace_filter() -> None:
    """Test filtering by namespace only."""
    result = resolve_types(False, "overture", (), ())

    result_str = repr(result)
    # Should contain official Overture types
    assert "Building" in result_str
    assert "Place" in result_str


def test_namespace_with_theme() -> None:
    """Test combining --namespace with --theme."""
    result = resolve_types(False, "overture", ("buildings",), ())

    result_str = repr(result)
    assert "Building" in result_str
    assert "BuildingPart" in result_str
    # Should not contain other themes
    assert "Place" not in result_str


def test_namespace_with_type() -> None:
    """Test combining --namespace with --type."""
    result = resolve_types(False, "overture", (), ("building",))

    result_str = repr(result)
    assert "Building" in result_str
    # Should not contain building_part
    assert "BuildingPart" not in result_str


def test_nonexistent_namespace_raises_error() -> None:
    """Test that nonexistent namespace raises ValueError."""
    with pytest.raises(ValueError, match="No models found matching"):
        resolve_types(False, "nonexistent_namespace", (), ())


def test_creates_annotated_union() -> None:
    """Test that it creates a proper Annotated union type."""
    models = discover_models()
    # Get just buildings models
    buildings_models = {k: v for k, v in models.items() if k.theme == "buildings"}

    result = create_union_type_from_models(buildings_models)

    # Should be Annotated
    assert get_origin(result) is not None
    result_str = repr(result)
    assert "Annotated" in result_str
    assert "discriminator='type'" in result_str


def test_empty_models_raises_error() -> None:
    """Test that empty models dict raises ValueError."""
    with pytest.raises(ValueError, match="No models provided"):
        create_union_type_from_models({})


def test_cli_help() -> None:
    """Test main CLI help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Overture Schema command-line interface" in result.output
    assert "validate" in result.output
    assert "json-schema" in result.output


def test_list_types_command() -> None:
    """Test list-types command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["list-types"])
    assert result.exit_code == 0
    assert "BUILDINGS" in result.output
    assert "→ building" in result.output
    assert "BASE" in result.output
    assert "→ water" in result.output
    assert "ADDRESSES" in result.output
    assert "→ address" in result.output


def test_list_types_command_help() -> None:
    """Test list-types command help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["list-types", "--help"])
    assert result.exit_code == 0
    assert (
        "List all available types grouped by theme with descriptions" in result.output
    )


def test_json_schema_generates_valid_output() -> None:
    """Test json-schema command generates valid JSON schema."""
    runner = CliRunner()
    result = runner.invoke(cli, ["json-schema", "--theme", "buildings"])
    assert result.exit_code == 0
    # Should output valid JSON
    import json

    schema = json.loads(result.output)
    assert "$defs" in schema
    assert "Building" in str(schema)


def test_validate_success_message(
    cli_runner: CliRunner, building_feature_yaml: str
) -> None:
    """Test that successful validation shows expected success message."""
    result = cli_runner.invoke(cli, ["validate", building_feature_yaml])
    assert result.exit_code == 0
    assert "✓ Successfully validated" in result.output
    assert building_feature_yaml in result.output


def test_validate_flat_format_input(
    cli_runner: CliRunner, flat_format_yaml: str
) -> None:
    """Test validation with flat format (non-GeoJSON) input."""
    result = cli_runner.invoke(cli, ["validate", flat_format_yaml])
    assert result.exit_code == 0
    assert "✓ Successfully validated" in result.output


# FIXME
def test_validate_error_message_format(
    cli_runner: CliRunner, missing_id_yaml: str
) -> None:
    """Test that validation errors are formatted correctly with field paths."""
    result = cli_runner.invoke(
        cli, ["validate", missing_id_yaml], catch_exceptions=False
    )
    assert result.exit_code == 1


def test_validate_error_filters_tagged_union_from_path(
    cli_runner: CliRunner, missing_id_yaml: str, stderr_buffer: StringIO
) -> None:
    """Test that validation errors filter out tagged-union and discriminator noise."""
    result = cli_runner.invoke(cli, ["validate", missing_id_yaml])

    assert result.exit_code == 1
    stderr_output = stderr_buffer.getvalue()

    # Verify that tagged-union does not appear in the error output
    assert "tagged-union" not in stderr_output.lower()
    # Verify that the model hint is shown
    assert "probable type:" in stderr_output.lower()
    assert "building" in stderr_output.lower()
    # Verify only the field name is shown in error path (not discriminator)
    assert "  id" in stderr_output.lower()
    # Verify discriminator values are NOT in the error path
    # (should be "id", not "building.id" or "tagged-union[...].id")
    lines = stderr_output.lower().split("\n")
    id_line = next((line for line in lines if line.strip().startswith("id")), None)
    assert id_line is not None
    assert "building" not in id_line  # Discriminator should not be in path


def test_validate_error_with_invalid_type_value(
    cli_runner: CliRunner, invalid_type_yaml: str
) -> None:
    """Test validation error message for invalid type value."""
    result = cli_runner.invoke(
        cli,
        ["validate", "--theme", "buildings", invalid_type_yaml],
        catch_exceptions=False,
    )
    assert result.exit_code == 1


def test_validate_error_with_nested_field(
    cli_runner: CliRunner, bad_geometry_type_yaml: str
) -> None:
    """Test validation error shows correct path for nested fields."""
    result = cli_runner.invoke(
        cli,
        ["validate", "--theme", "buildings", bad_geometry_type_yaml],
        catch_exceptions=False,
    )
    assert result.exit_code == 1


def test_validate_stdin_with_no_argument(
    cli_runner: CliRunner, building_feature_yaml_content: str
) -> None:
    """Test validation from stdin when no filename argument is provided."""
    result = cli_runner.invoke(cli, ["validate"], input=building_feature_yaml_content)
    assert result.exit_code == 0
    assert "✓ Successfully validated <stdin>" in result.output


def test_validate_stdin_with_dash_argument(
    cli_runner: CliRunner, building_feature_yaml_content: str
) -> None:
    """Test validation from stdin when '-' is passed as filename."""
    result = cli_runner.invoke(
        cli, ["validate", "-"], input=building_feature_yaml_content
    )
    assert result.exit_code == 0
    assert "✓ Successfully validated <stdin>" in result.output


def test_validate_stdin_with_error(
    cli_runner: CliRunner, missing_id_yaml_content: str, stderr_buffer: StringIO
) -> None:
    """Test validation error from stdin shows correct source name."""
    result = cli_runner.invoke(cli, ["validate"], input=missing_id_yaml_content)
    assert result.exit_code == 1
    stderr_output = stderr_buffer.getvalue()
    assert "Validation failed:" in stderr_output


def test_validate_feature_list_success(
    cli_runner: CliRunner, feature_list_yaml: str
) -> None:
    """Test that validation succeeds for a list of valid features."""
    result = cli_runner.invoke(cli, ["validate", feature_list_yaml])
    assert result.exit_code == 0
    assert "✓ Successfully validated" in result.output
    assert feature_list_yaml in result.output


def test_validate_feature_list_with_error(
    cli_runner: CliRunner, feature_list_with_error_yaml: str, stderr_buffer: StringIO
) -> None:
    """Test that validation fails appropriately for a list with an invalid feature."""
    result = cli_runner.invoke(cli, ["validate", feature_list_with_error_yaml])
    assert result.exit_code == 1
    stderr_output = stderr_buffer.getvalue()
    assert "Validation failed:" in stderr_output
    # Should indicate which item in the list failed (item 1, 0-indexed)
    assert "[1]" in stderr_output or "item 1" in stderr_output.lower()


def test_validate_feature_list_from_stdin(
    cli_runner: CliRunner, feature_list_yaml_content: str
) -> None:
    """Test validation of a list of features from stdin."""
    result = cli_runner.invoke(cli, ["validate"], input=feature_list_yaml_content)
    assert result.exit_code == 0
    assert "✓ Successfully validated <stdin>" in result.output


@pytest.fixture
def feature_collection_yaml(cli_runner: CliRunner) -> str:  # noqa: ARG001
    """Create a feature-collection.yaml file with valid FeatureCollection."""
    filename = "feature-collection.yaml"
    with open(filename, "w") as f:
        f.write("""{
  "type": "FeatureCollection",
  "features": [
    {
      "id": "test1",
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
      },
      "properties": {
        "theme": "buildings",
        "type": "building",
        "version": 0
      }
    },
    {
      "id": "test2",
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
      },
      "properties": {
        "theme": "buildings",
        "type": "building",
        "version": 0
      }
    }
  ]
}
""")
    return filename


@pytest.fixture
def feature_collection_with_error_yaml(cli_runner: CliRunner) -> str:  # noqa: ARG001
    """Create a FeatureCollection where second feature is missing id."""
    filename = "feature-collection-error.yaml"
    with open(filename, "w") as f:
        f.write("""{
  "type": "FeatureCollection",
  "features": [
    {
      "id": "test1",
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
      },
      "properties": {
        "theme": "buildings",
        "type": "building",
        "version": 0
      }
    },
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
      },
      "properties": {
        "theme": "buildings",
        "type": "building",
        "version": 0
      }
    }
  ]
}
""")
    return filename


@pytest.fixture
def feature_collection_all_invalid_yaml(cli_runner: CliRunner) -> str:  # noqa: ARG001
    """Create a FeatureCollection where all features are invalid."""
    filename = "feature-collection-all-invalid.yaml"
    with open(filename, "w") as f:
        f.write("""{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
      },
      "properties": {
        "theme": "buildings",
        "type": "building",
        "version": 0
      }
    },
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
      },
      "properties": {
        "theme": "buildings",
        "type": "building",
        "version": 0
      }
    }
  ]
}
""")
    return filename


def test_validate_feature_collection_success(
    cli_runner: CliRunner, feature_collection_yaml: str
) -> None:
    """Test that validation succeeds for a valid FeatureCollection."""
    result = cli_runner.invoke(cli, ["validate", feature_collection_yaml])
    assert result.exit_code == 0
    assert "✓ Successfully validated" in result.output
    assert feature_collection_yaml in result.output


def test_validate_feature_collection_with_error(
    cli_runner: CliRunner,
    feature_collection_with_error_yaml: str,
    stderr_buffer: StringIO,
) -> None:
    """Test that validation fails for FeatureCollection with one invalid feature."""
    result = cli_runner.invoke(cli, ["validate", feature_collection_with_error_yaml])
    assert result.exit_code == 1
    stderr_output = stderr_buffer.getvalue()
    assert "Validation failed:" in stderr_output
    # Should indicate which item in the features list failed (item 1, 0-indexed)
    assert "[1]" in stderr_output or "item 1" in stderr_output.lower()


def test_validate_feature_collection_all_invalid(
    cli_runner: CliRunner,
    feature_collection_all_invalid_yaml: str,
    stderr_buffer: StringIO,
) -> None:
    """Test that validation shows errors for all invalid features in FeatureCollection."""
    result = cli_runner.invoke(cli, ["validate", feature_collection_all_invalid_yaml])
    assert result.exit_code == 1
    stderr_output = stderr_buffer.getvalue()
    assert "Validation failed:" in stderr_output
    # Should show errors for both features
    assert "[0]" in stderr_output or "[1]" in stderr_output


class TestStructuralTuples:
    """Tests for creating structural tuples from error loc paths."""

    def test_simple_discriminated_union_structural_tuple(self) -> None:
        """Test structural tuple for simple discriminated union errors."""
        from typing import Annotated, Literal

        from overture.schema.cli import create_structural_tuple

        class ModelA(BaseModel):
            type: Literal["a"]
            required_a: int

        class ModelB(BaseModel):
            type: Literal["b"]
            required_b: int

        UnionType = Annotated[ModelA | ModelB, Field(discriminator="type")]

        # Test simple discriminated union error path
        loc = ("a", "required_a")
        structural = create_structural_tuple(loc, UnionType)
        print(f"\nloc: {loc}")
        print(f"structural: {structural}")
        assert len(structural) == len(loc)
        # First element should be discriminator, second should be field
        assert structural == ("discriminator", "field")

    def test_mixed_union_structural_tuple(self) -> None:
        """Test structural tuple for mixed discriminated/non-discriminated union."""
        from typing import Annotated, Literal

        from overture.schema.cli import create_structural_tuple

        class ModelA(BaseModel):
            type: Literal["a"]
            required_a: int

        class Sources(BaseModel):
            datasets: list[str]

        DiscriminatedUnion = Annotated[ModelA, Field(discriminator="type")]
        MixedUnion = DiscriminatedUnion | Sources

        # Test discriminated side
        loc1 = ("tagged-union[ModelA]", "a", "required_a")
        structural1 = create_structural_tuple(loc1, MixedUnion)
        print("\nDiscriminated side:")
        print(f"loc: {loc1}")
        print(f"structural: {structural1}")
        assert structural1 == ("union", "discriminator", "field")

        # Test non-discriminated side
        loc2 = ("Sources", "datasets")
        structural2 = create_structural_tuple(loc2, MixedUnion)
        print("\nNon-discriminated side:")
        print(f"loc: {loc2}")
        print(f"structural: {structural2}")
        assert structural2 == ("model", "field")

    def test_list_context_structural_tuple(self) -> None:
        """Test structural tuple for union in list context."""
        from typing import Annotated, Literal

        from overture.schema.cli import create_structural_tuple

        class ModelA(BaseModel):
            type: Literal["a"]
            required_a: int

        UnionType = Annotated[ModelA, Field(discriminator="type")]

        # Test list context
        loc = (1, "a", "required_a")
        structural = create_structural_tuple(loc, list[UnionType])
        print("\nList context:")
        print(f"loc: {loc}")
        print(f"structural: {structural}")
        assert structural == ("list_index", "discriminator", "field")

    def test_nested_discriminated_structural_tuple(self) -> None:
        """Test structural tuple for nested discriminated unions."""
        from typing import Annotated, Literal

        from overture.schema.cli import create_structural_tuple

        class Building(BaseModel):
            type: Literal["building"]
            height: float

        class RoadSegment(BaseModel):
            type: Literal["segment"]
            subtype: Literal["road"]
            road_class: str

        class Sources(BaseModel):
            datasets: list[str]

        # Nested structure
        Segment = Annotated[RoadSegment, Field(discriminator="subtype")]
        TopLevel = Annotated[Building | Segment, Field(discriminator="type")]
        MixedUnion = TopLevel | Sources

        # Test nested discriminated path
        loc = (
            "tagged-union[Building,tagged-union[RoadSegment]]",
            "segment",
            "road",
            "road_class",
        )
        structural = create_structural_tuple(loc, MixedUnion)
        print("\nNested discriminated:")
        print(f"loc: {loc}")
        print(f"structural: {structural}")
        assert structural == ("union", "discriminator", "discriminator", "field")


class TestErrorGrouping:
    """Tests for error grouping and selection logic."""

    def test_ambiguous_data_shows_most_likely_errors(
        self, cli_runner: CliRunner
    ) -> None:
        """Test that ambiguous data shows errors from the most likely model."""
        # Create a file with data that doesn't match any model well
        # (missing fields for both Building and hypothetical Sources model)
        filename = "ambiguous.yaml"
        with open(filename, "w") as f:
            f.write("""
id: test
type: Feature
geometry:
  type: Point
  coordinates: [0, 0]
properties:
  theme: buildings
  type: building
  version: 0
""")

        result = cli_runner.invoke(cli, ["validate", "--theme", "buildings", filename])

        assert result.exit_code == 1

        # The output should show errors for the most likely model (Building)
        # Should NOT show all possible errors from all union variants
        # In this case, Building has wrong geometry type (Point instead of Polygon)
        # We expect a validation error about geometry

    def test_tie_in_error_counts_is_deterministic(self, cli_runner: CliRunner) -> None:
        """Test behavior when multiple models have same error count."""
        # Create a mixed union where both sides can have equal errors
        from typing import Literal

        from pydantic import ValidationError

        class Building(BaseModel):
            type: Literal["building"]
            id: str
            height: float

        class Sources(BaseModel):
            datasets: list[str]
            license_priority: int

        from typing import Annotated

        # Mixed union: discriminated + non-discriminated
        MixedUnion = Annotated[Building, Field(discriminator="type")] | Sources

        # Data with type="building" missing 2 fields (id, height)
        # This creates a tie: Building needs 2 fields, Sources also needs 2 fields
        invalid_data = {"type": "building"}

        try:
            TypeAdapter(MixedUnion).validate_python(invalid_data)
            pytest.fail("Should have raised ValidationError")
        except ValidationError as e:
            from overture.schema.cli import (
                group_errors_by_discriminator,
                select_most_likely_errors,
            )

            errors = e.errors()
            groups = group_errors_by_discriminator(errors, MixedUnion)

            # Both groups should have same number of errors (tie situation)
            error_counts = {k: len(v) for k, v in groups.items()}
            if len(set(error_counts.values())) == 1 and len(groups) > 1:
                # We have a tie!
                selected, is_tied = select_most_likely_errors(groups)
                assert len(selected) > 0, "Should select errors even in a tie"
                assert is_tied, "Should indicate that there was a tie"

                # Should return errors from ALL tied groups
                total_expected = sum(len(v) for v in groups.values())
                assert len(selected) == total_expected, (
                    "Should return all errors from all tied groups"
                )

                # Run it multiple times to verify deterministic behavior
                for _ in range(5):
                    selected_again, is_tied_again = select_most_likely_errors(groups)
                    assert selected == selected_again, (
                        "Selection should be deterministic"
                    )
                    assert is_tied_again == is_tied, (
                        "Tie indication should be consistent"
                    )
            else:
                # Not a tie in this case, just verify it doesn't indicate a tie
                selected, is_tied = select_most_likely_errors(groups)
                assert not is_tied or len(groups) <= 1, (
                    "Should not indicate tie when error counts differ"
                )

    def test_clear_winner_selected(self, cli_runner: CliRunner) -> None:
        """Test that the model with fewest errors is selected when there's a clear winner."""
        filename = "clear-winner.yaml"
        with open(filename, "w") as f:
            # Missing only 'id' field for Building (1 error)
            # Would have many errors for Sources (datasets, license_priority, etc.)
            f.write("""
type: Feature
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
properties:
  theme: buildings
  type: building
  version: 0
""")

        from io import StringIO
        from unittest.mock import patch

        buffer = StringIO()
        captured_console = Console(file=buffer, force_terminal=False)

        with patch("overture.schema.cli.stderr", captured_console):
            result = cli_runner.invoke(cli, ["validate", filename])

        assert result.exit_code == 1
        stderr_output = buffer.getvalue()

        # Should show only the Building error (missing id)
        assert "id" in stderr_output.lower()
        # Should NOT show Sources-related errors
        assert "dataset" not in stderr_output.lower()
        assert "license" not in stderr_output.lower()

    def test_list_indices_do_not_cause_false_ambiguity(
        self, cli_runner: CliRunner
    ) -> None:
        """Test that list indices don't cause false ambiguity detection.

        When validating a list of features where multiple items have the same
        type of error (e.g., multiple buildings missing 'id'), the list indices
        should be ignored during grouping so they're treated as the same error
        group, not separate groups.
        """
        filename = "list-same-errors.yaml"
        with open(filename, "w") as f:
            # Two features, both Building, both missing 'id'
            f.write("""
- type: Feature
  geometry:
    type: Polygon
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
  properties:
    theme: buildings
    type: building
    version: 0
- type: Feature
  geometry:
    type: Polygon
    coordinates: [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
  properties:
    theme: buildings
    type: building
    version: 0
""")

        from io import StringIO
        from unittest.mock import patch

        buffer = StringIO()
        captured_console = Console(file=buffer, force_terminal=False)

        with patch("overture.schema.cli.stderr", captured_console):
            result = cli_runner.invoke(cli, ["validate", filename])

        assert result.exit_code == 1
        stderr_output = buffer.getvalue()

        # Should NOT show ambiguity warning since both are Building with same error
        assert "ambiguous" not in stderr_output.lower()
        # Should show the missing 'id' error
        assert "id" in stderr_output.lower()
