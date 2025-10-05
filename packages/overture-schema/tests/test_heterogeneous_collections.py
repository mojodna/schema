"""Tests for heterogeneous collection validation."""

from io import StringIO

import pytest
from click.testing import CliRunner
from overture.schema.cli.commands import cli


@pytest.fixture
def heterogeneous_collection_yaml() -> str:
    """A collection mixing buildings and places."""
    return """
- id: building-1
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
  properties:
    theme: buildings
    type: building
    version: 0
- id: place-1
  type: Feature
  geometry:
    type: Point
    coordinates: [0.5, 0.5]
  properties:
    theme: places
    type: place
    version: 0
    operating_status: open
    categories:
      primary: restaurant
    names:
      primary: "Valid Place"
"""


@pytest.fixture
def heterogeneous_with_missing_fields_yaml() -> str:
    """A collection where minority type has errors."""
    return """
- id: building-valid-1
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
  properties:
    theme: buildings
    type: building
    version: 0
    names:
      primary: "Valid Building"
- type: Feature
  geometry:
    type: Polygon
    coordinates: [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
  properties:
    theme: buildings
    type: building
    version: 0
    names:
      primary: "Missing ID Building"
- id: building-bad-geometry-3
  type: Feature
  geometry:
    type: InvalidGeometryType
    coordinates: [[[4, 4], [5, 4], [5, 5], [4, 5], [4, 4]]]
  properties:
    theme: buildings
    type: building
    version: 0
- type: Feature
  geometry:
    type: Point
    coordinates: [6.5, 6.5]
  properties:
    theme: places
    type: place
    version: 0
    categories:
      primary: restaurant
    names:
      primary: "Place missing required field"
"""


class TestHeterogeneousCollections:
    """Tests for heterogeneous collection handling."""

    def test_heterogeneous_collection_success(
        self, cli_runner: CliRunner, heterogeneous_collection_yaml: str
    ) -> None:
        """Test that valid heterogeneous collections pass validation."""
        result = cli_runner.invoke(
            cli, ["validate"], input=heterogeneous_collection_yaml
        )
        assert result.exit_code == 0
        assert "Successfully validated" in result.output

    def test_heterogeneous_collection_shows_all_errors(
        self,
        cli_runner: CliRunner,
        heterogeneous_with_missing_fields_yaml: str,
        stderr_buffer: StringIO,
    ) -> None:
        """Test that errors from minority types are shown, not hidden."""
        result = cli_runner.invoke(
            cli, ["validate"], input=heterogeneous_with_missing_fields_yaml
        )
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()

        # Should show errors for buildings (items 1 and 2)
        assert "[1]" in stderr_output or "1" in stderr_output
        assert "[2]" in stderr_output or "2" in stderr_output

        # Should show error for place (item 3)
        assert "[3]" in stderr_output or "3" in stderr_output

        # Should show building-specific errors
        assert "id" in stderr_output.lower()  # Missing ID for building

        # Should show geometry error
        assert "geometry" in stderr_output.lower()

    def test_heterogeneous_collection_warns_about_heterogeneity(
        self,
        cli_runner: CliRunner,
        heterogeneous_with_missing_fields_yaml: str,
        stderr_buffer: StringIO,
    ) -> None:
        """Test that heterogeneous collections trigger a warning."""
        result = cli_runner.invoke(
            cli, ["validate"], input=heterogeneous_with_missing_fields_yaml
        )
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()

        # Should warn about heterogeneity
        assert (
            "heterogeneous" in stderr_output.lower()
            or "mixed types" in stderr_output.lower()
        )

    def test_homogeneous_collection_no_warning(
        self, cli_runner: CliRunner, stderr_buffer: StringIO
    ) -> None:
        """Test that homogeneous collections don't trigger heterogeneity warning."""
        homogeneous_yaml = """
- id: building-1
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
"""
        result = cli_runner.invoke(cli, ["validate"], input=homogeneous_yaml)
        assert result.exit_code == 1  # Has error (missing id)

        stderr_output = stderr_buffer.getvalue()

        # Should NOT warn about heterogeneity
        assert "heterogeneous" not in stderr_output.lower()
        assert "mixed types" not in stderr_output.lower()

    def test_heterogeneous_prefers_majority_type_for_ambiguous_items(
        self,
        cli_runner: CliRunner,
        stderr_buffer: StringIO,
    ) -> None:
        """Test that ambiguous items are interpreted as the majority type."""
        # Create a collection where one item could be either type but is missing
        # fields that would make it valid for either. The majority type should
        # be used for interpretation.
        ambiguous_yaml = """
- id: building-1
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
  properties:
    theme: buildings
    type: building
    version: 0
- id: building-2
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
  properties:
    theme: buildings
    type: building
    version: 0
- id: ambiguous-3
  type: Feature
  geometry:
    type: Polygon
    coordinates: [[[4, 4], [5, 4], [5, 5], [4, 5], [4, 4]]]
  properties:
    version: 0
"""
        result = cli_runner.invoke(cli, ["validate"], input=ambiguous_yaml)
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()

        # The ambiguous item should be interpreted as a building (majority type)
        # and should show errors for missing building fields
        assert "[2]" in stderr_output
        assert "theme" in stderr_output.lower() or "type" in stderr_output.lower()
