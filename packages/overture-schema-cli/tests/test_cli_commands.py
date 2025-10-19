"""Tests for CLI commands (validate, list-types, json-schema)."""

import json
from io import StringIO

import pytest
from click.testing import CliRunner
from conftest import build_feature
from overture.schema.cli.commands import cli


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

    def test_validate_flat_format_input(self, cli_runner: CliRunner) -> None:
        """Test that validation works with flat (non-GeoJSON) format."""
        flat_feature = build_feature(geojson_format=False)
        flat_json = json.dumps(flat_feature)
        result = cli_runner.invoke(
            cli, ["validate", "--theme", "buildings", "-"], input=flat_json
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
        result = cli_runner.invoke(
            cli, ["validate", "-"], input=missing_id_yaml_content
        )
        assert result.exit_code == 1

        stderr_output = stderr_buffer.getvalue()
        assert "Validation Failed" in stderr_output
        # Should show the field path
        assert "id" in stderr_output.lower()

    def test_validate_error_filters_tagged_union_from_path(
        self,
        cli_runner: CliRunner,
        missing_id_yaml_content: str,
        stderr_buffer: StringIO,
    ) -> None:
        """Test that validation error paths don't show internal tagged-union markers."""
        result = cli_runner.invoke(
            cli, ["validate", "-"], input=missing_id_yaml_content
        )
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
        invalid_feature = build_feature(type="invalid_type")
        invalid_type_json = json.dumps(invalid_feature)
        result = cli_runner.invoke(cli, ["validate", "-"], input=invalid_type_json)
        assert result.exit_code == 1

    def test_validate_error_with_nested_field(self, cli_runner: CliRunner) -> None:
        """Test validation error message includes nested field path."""
        feature = build_feature(
            names={
                "common": [
                    {"value": "Test Building", "language": "invalid_language_code"}
                ]
            }
        )
        nested_field_json = json.dumps(feature)
        result = cli_runner.invoke(cli, ["validate", "-"], input=nested_field_json)
        assert result.exit_code == 1

    def test_validate_stdin_requires_dash_argument(
        self,
        cli_runner: CliRunner,
        building_feature_yaml_content: str,
    ) -> None:
        """Test validating from stdin requires explicit '-' argument."""
        # With dash argument - should work
        result = cli_runner.invoke(
            cli, ["validate", "-"], input=building_feature_yaml_content
        )
        assert result.exit_code == 0
        assert "Successfully validated <stdin>" in result.output

        # Without dash argument - should show help/usage
        result = cli_runner.invoke(
            cli, ["validate"], input=building_feature_yaml_content
        )
        assert result.exit_code == 2  # Usage error
        assert "Missing argument" in result.output or "Usage:" in result.output

    @pytest.mark.parametrize(
        "has_error,expected_exit_code,check_index",
        [
            pytest.param(False, 0, False, id="success"),
            pytest.param(True, 1, True, id="with_error"),
        ],
    )
    def test_validate_feature_list(
        self,
        cli_runner: CliRunner,
        stderr_buffer: StringIO,
        has_error: bool,
        expected_exit_code: int,
        check_index: bool,
    ) -> None:
        """Test validation of a list of features (success and error cases)."""
        feature1 = build_feature(id="test1")
        feature2_id = None if has_error else "test2"
        feature2 = build_feature(
            id=feature2_id, coordinates=[[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]]
        )
        feature_list_json = json.dumps([feature1, feature2])
        result = cli_runner.invoke(cli, ["validate", "-"], input=feature_list_json)
        assert result.exit_code == expected_exit_code

        if check_index:
            stderr_output = stderr_buffer.getvalue()
            # Should show list index for the second feature
            assert "[1]" in stderr_output or "1" in stderr_output
        else:
            assert "Successfully validated <stdin>" in result.output

    @pytest.mark.parametrize(
        "first_feature_valid,second_feature_valid,expected_exit_code",
        [
            pytest.param(True, True, 0, id="both_valid"),
            pytest.param(True, False, 1, id="second_invalid"),
            pytest.param(False, False, 1, id="both_invalid"),
        ],
    )
    def test_validate_feature_collection(
        self,
        cli_runner: CliRunner,
        stderr_buffer: StringIO,
        first_feature_valid: bool,
        second_feature_valid: bool,
        expected_exit_code: int,
    ) -> None:
        """Test validation of a GeoJSON FeatureCollection with various validity states."""
        feature1 = build_feature(id="test1" if first_feature_valid else None)
        feature2 = build_feature(
            id="test2" if second_feature_valid else None,
            coordinates=[[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]],
        )
        feature_collection = {
            "type": "FeatureCollection",
            "features": [feature1, feature2],
        }
        result = cli_runner.invoke(
            cli, ["validate", "-"], input=json.dumps(feature_collection)
        )
        assert result.exit_code == expected_exit_code

        if expected_exit_code == 0:
            assert "Successfully validated <stdin>" in result.output
        else:
            stderr_output = stderr_buffer.getvalue()
            # Should show errors for list items
            if not first_feature_valid or not second_feature_valid:
                assert "[0]" in stderr_output or "[1]" in stderr_output

    def test_validate_with_nonexistent_filters_raises_error(
        self,
        cli_runner: CliRunner,
        building_feature_yaml_content: str,
    ) -> None:
        """Test that validation with filters matching no models raises a clear error."""
        # Try to validate with a nonexistent theme
        result = cli_runner.invoke(
            cli,
            ["validate", "--theme", "nonexistent_theme", "-"],
            input=building_feature_yaml_content,
        )
        # UsageError exits with code 2
        assert result.exit_code == 2
        assert "No models found matching the specified criteria" in result.output

    def test_validate_with_nonexistent_type_raises_error(
        self,
        cli_runner: CliRunner,
        building_feature_yaml_content: str,
    ) -> None:
        """Test that validation with nonexistent type raises a clear error."""
        # Try to validate with a nonexistent type
        result = cli_runner.invoke(
            cli,
            ["validate", "--type", "nonexistent_type", "-"],
            input=building_feature_yaml_content,
        )
        # UsageError exits with code 2
        assert result.exit_code == 2
        assert "No models found matching the specified criteria" in result.output

    def test_validate_with_valid_theme_invalid_type_raises_error(
        self,
        cli_runner: CliRunner,
        building_feature_yaml_content: str,
    ) -> None:
        """Test that validation with valid theme but invalid type raises an error."""
        # Try to validate buildings theme with a type that doesn't exist in that theme
        result = cli_runner.invoke(
            cli,
            ["validate", "--theme", "buildings", "--type", "segment", "-"],
            input=building_feature_yaml_content,
        )
        # UsageError exits with code 2
        assert result.exit_code == 2
        assert "No models found matching the specified criteria" in result.output
