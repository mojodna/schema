"""Tests for CLI commands (validate, list-types, json-schema)."""

import json
from collections.abc import Generator
from io import StringIO
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from overture.schema.cli.commands import cli
from rich.console import Console


class TestListTypesCommand:
    """Tests for the list-types command."""

    def test_list_types_command(self, cli_runner: CliRunner) -> None:
        """Test the list-types command."""
        result = cli_runner.invoke(cli, ["list-types"])
        assert result.exit_code == 0
        # Should show theme names
        assert "BUILDINGS" in result.output or "buildings" in result.output
        # Should show type names
        assert "building" in result.output

    def test_list_types_command_help(self, cli_runner: CliRunner) -> None:
        """Test list-types command help."""
        result = cli_runner.invoke(cli, ["list-types", "--help"])
        assert result.exit_code == 0
        assert "list-types" in result.output.lower()


class TestJsonSchemaCommand:
    """Tests for the json-schema command."""

    def test_json_schema_generates_valid_output(self, cli_runner: CliRunner) -> None:
        """Test that json-schema command generates valid JSON."""
        result = cli_runner.invoke(cli, ["json-schema", "--theme", "buildings"])
        assert result.exit_code == 0

        # Should be valid JSON
        schema = json.loads(result.output)
        assert isinstance(schema, dict)


class TestValidateCommand:
    """Tests for the validate command."""

    def test_validate_success_message_from_file(
        self, cli_runner: CliRunner, building_feature_yaml: str
    ) -> None:
        """Test that validation shows success message for valid file input."""
        result = cli_runner.invoke(cli, ["validate", building_feature_yaml])
        assert result.exit_code == 0
        assert "Successfully validated" in result.output

    def test_validate_success_message(
        self, cli_runner: CliRunner, building_feature_yaml_content: str
    ) -> None:
        """Test that validation shows success message for valid input."""
        result = cli_runner.invoke(
            cli, ["validate"], input=building_feature_yaml_content
        )
        assert result.exit_code == 0
        assert "Successfully validated <stdin>" in result.output

    def test_validate_flat_format_input(self, cli_runner: CliRunner) -> None:
        """Test that validation works with flat (non-GeoJSON) format."""
        flat_yaml = """
id: test
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
theme: buildings
type: building
version: 0
"""
        result = cli_runner.invoke(
            cli, ["validate", "--theme", "buildings"], input=flat_yaml
        )
        assert result.exit_code == 0
        assert "Successfully validated <stdin>" in result.output

    def test_validate_error_message_format(
        self,
        cli_runner: CliRunner,
        missing_id_yaml_content: str,
        stderr_buffer: StringIO,
    ) -> None:
        """Test that validation errors are formatted correctly."""
        result = cli_runner.invoke(cli, ["validate"], input=missing_id_yaml_content)
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()
        assert "Validation failed" in stderr_output
        # Should show the field path
        assert "id" in stderr_output.lower()

    def test_validate_error_filters_tagged_union_from_path(
        self,
        cli_runner: CliRunner,
        missing_id_yaml_content: str,
        stderr_buffer: StringIO,
    ) -> None:
        """Test that validation error paths don't show internal tagged-union markers."""
        result = cli_runner.invoke(cli, ["validate"], input=missing_id_yaml_content)
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()

        # Should NOT show Pydantic's internal union markers in the path
        assert "tagged-union" not in stderr_output.lower()
        assert "union[" not in stderr_output.lower()

        # Should show the actual field name
        assert "id" in stderr_output.lower()

    def test_validate_error_with_invalid_type_value(
        self, cli_runner: CliRunner
    ) -> None:
        """Test validation error for invalid type value."""
        invalid_type_yaml = """
id: test
type: Feature
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
properties:
  theme: buildings
  type: invalid_type
  version: 0
"""
        result = cli_runner.invoke(cli, ["validate"], input=invalid_type_yaml)
        assert result.exit_code == 1

    def test_validate_error_with_nested_field(self, cli_runner: CliRunner) -> None:
        """Test validation error message includes nested field path."""
        nested_field_yaml = """
id: test
type: Feature
geometry:
  type: Polygon
  coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]
properties:
  theme: buildings
  type: building
  version: 0
  names:
    common:
      - value: "Test Building"
        language: invalid_language_code
"""
        result = cli_runner.invoke(cli, ["validate"], input=nested_field_yaml)
        assert result.exit_code == 1

    def test_validate_stdin_with_no_argument(
        self, cli_runner: CliRunner, building_feature_yaml_content: str
    ) -> None:
        """Test validating from stdin when no filename is provided."""
        result = cli_runner.invoke(
            cli, ["validate"], input=building_feature_yaml_content
        )
        assert result.exit_code == 0
        assert "Successfully validated <stdin>" in result.output

    def test_validate_stdin_with_dash_argument(
        self, cli_runner: CliRunner, building_feature_yaml_content: str
    ) -> None:
        """Test validating from stdin using '-' as filename."""
        result = cli_runner.invoke(
            cli, ["validate", "-"], input=building_feature_yaml_content
        )
        assert result.exit_code == 0
        assert "Successfully validated <stdin>" in result.output

    def test_validate_stdin_with_error(
        self,
        cli_runner: CliRunner,
        missing_id_yaml_content: str,
        stderr_buffer: StringIO,
    ) -> None:
        """Test that validation errors from stdin are shown correctly."""
        result = cli_runner.invoke(cli, ["validate"], input=missing_id_yaml_content)
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()
        assert "Validation failed" in stderr_output

    def test_validate_feature_list_success(self, cli_runner: CliRunner) -> None:
        """Test validation of a list of features."""
        feature_list = """
- id: test1
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
        result = cli_runner.invoke(cli, ["validate"], input=feature_list)
        assert result.exit_code == 0
        assert "Successfully validated <stdin>" in result.output

    def test_validate_feature_list_with_error(
        self,
        cli_runner: CliRunner,
        stderr_buffer: StringIO,
    ) -> None:
        """Test validation error in feature list shows the list index."""
        feature_list_with_error = """
- id: test1
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
        result = cli_runner.invoke(cli, ["validate"], input=feature_list_with_error)
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()
        # Should show list index for the second feature
        assert "[1]" in stderr_output or "1" in stderr_output

    def test_validate_feature_list_from_stdin(self, cli_runner: CliRunner) -> None:
        """Test validation of feature list from stdin."""
        yaml_content = """
- id: test1
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
        result = cli_runner.invoke(cli, ["validate"], input=yaml_content)
        assert result.exit_code == 0

    def test_validate_feature_collection_success(self, cli_runner: CliRunner) -> None:
        """Test validation of a GeoJSON FeatureCollection."""
        feature_collection = """
type: FeatureCollection
features:
  - id: test1
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
        result = cli_runner.invoke(cli, ["validate"], input=feature_collection)
        assert result.exit_code == 0
        assert "Successfully validated <stdin>" in result.output

    def test_validate_feature_collection_with_error(
        self, cli_runner: CliRunner, stderr_buffer: StringIO
    ) -> None:
        """Test validation error in FeatureCollection."""
        feature_collection_error = """
type: FeatureCollection
features:
  - id: test1
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
        result = cli_runner.invoke(cli, ["validate"], input=feature_collection_error)
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()
        assert "Validation failed" in stderr_output

    def test_validate_feature_collection_all_invalid(
        self, cli_runner: CliRunner, stderr_buffer: StringIO
    ) -> None:
        """Test validation when all features in FeatureCollection are invalid."""
        feature_collection_all_invalid = """
type: FeatureCollection
features:
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
"""
        result = cli_runner.invoke(
            cli, ["validate"], input=feature_collection_all_invalid
        )
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()
        # Should show errors for list items
        assert "[0]" in stderr_output or "[1]" in stderr_output
