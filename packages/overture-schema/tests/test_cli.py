"""Tests for the CLI functionality."""

from collections.abc import Generator
from io import StringIO
from typing import get_origin
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from overture.schema.cli import cli, create_union_type_from_models, resolve_types
from overture.schema.core.discovery import discover_models
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
    """Test that validation errors filter out tagged-union noise from paths."""
    result = cli_runner.invoke(cli, ["validate", missing_id_yaml])

    assert result.exit_code == 1
    stderr_output = stderr_buffer.getvalue()

    # Verify that tagged-union does not appear in the error output
    assert "tagged-union" not in stderr_output.lower()
    # Verify the clean path is shown
    assert "building.id" in stderr_output.lower()


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
