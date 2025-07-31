"""Tests for the CLI functionality."""

from typing import get_origin

import pytest
from click.testing import CliRunner
from overture.schema.cli import cli, create_union_type_from_models, resolve_types
from overture.schema.core.discovery import discover_models


class TestResolveTypes:
    """Test the resolve_types function."""

    def test_overture_types_option(self) -> None:
        """Test --overture-types returns the official Types union."""
        result = resolve_types((), (), True)

        # Should be an Annotated type
        assert get_origin(result) is not None

        # Should contain all the official Overture types
        result_str = repr(result)
        assert "Address" in result_str
        assert "Building" in result_str
        assert "Place" in result_str

    def test_theme_only_filter(self) -> None:
        """Test filtering by theme only."""
        result = resolve_types((), ("buildings",), False)

        result_str = repr(result)
        assert "Building" in result_str
        assert "BuildingPart" in result_str
        # Should not contain other themes
        assert "Address" not in result_str
        assert "Place" not in result_str

    def test_type_only_filter(self) -> None:
        """Test filtering by type only."""
        result = resolve_types(("building",), (), False)

        result_str = repr(result)
        assert "Building" in result_str
        # Should not contain building_part
        assert "BuildingPart" not in result_str

    def test_theme_and_type_filter(self) -> None:
        """Test filtering by both theme and type."""
        result = resolve_types(("building",), ("buildings",), False)

        result_str = repr(result)
        assert "Building" in result_str
        # Should not contain building_part or other types
        assert "BuildingPart" not in result_str
        assert "Place" not in result_str

    def test_multiple_types(self) -> None:
        """Test filtering by multiple types."""
        result = resolve_types(("building", "place"), (), False)

        result_str = repr(result)
        assert "Building" in result_str
        assert "Place" in result_str
        assert "BuildingPart" not in result_str

    def test_multiple_themes(self) -> None:
        """Test filtering by multiple themes."""
        result = resolve_types((), ("buildings", "places"), False)

        result_str = repr(result)
        assert "Building" in result_str
        assert "BuildingPart" in result_str
        assert "Place" in result_str
        # Should not contain other themes
        assert "Address" not in result_str

    def test_no_filters_uses_all_models(self) -> None:
        """Test that no filters returns all discovered models."""
        result = resolve_types((), (), False)

        result_str = repr(result)
        # Should contain models from multiple themes
        assert "Building" in result_str
        assert "Place" in result_str
        assert "Address" in result_str

    def test_nonexistent_type_raises_error(self) -> None:
        """Test that nonexistent type raises ValueError."""
        with pytest.raises(ValueError, match="No models found matching"):
            resolve_types(("nonexistent",), (), False)

    def test_nonexistent_theme_raises_error(self) -> None:
        """Test that nonexistent theme raises ValueError."""
        with pytest.raises(ValueError, match="No models found matching"):
            resolve_types((), ("nonexistent",), False)


class TestCreateUnionTypeFromModels:
    """Test the create_union_type_from_models helper function."""

    def test_creates_annotated_union(self) -> None:
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

    def test_empty_models_raises_error(self) -> None:
        """Test that empty models dict raises ValueError."""
        with pytest.raises(ValueError, match="No models provided"):
            create_union_type_from_models({})


class TestCLI:
    """Test the CLI commands."""

    def setUp(self) -> None:
        """Set up test runner."""
        self.runner = CliRunner()

    def test_validate_command_exists(self) -> None:
        """Test that validate command is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Validate Overture Maps data against schemas" in result.output

    def test_json_schema_command_exists(self) -> None:
        """Test that json-schema command is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["json-schema", "--help"])
        assert result.exit_code == 0
        assert "Generate JSON schema for Overture Maps types" in result.output

    def test_validate_with_overture_types(self) -> None:
        """Test validate command with --overture-types option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "--overture-types"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output
        assert "Model type resolved:" in result.output

    def test_validate_with_theme(self) -> None:
        """Test validate command with --theme option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "--theme", "buildings"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_validate_with_type(self) -> None:
        """Test validate command with --type option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "--type", "building"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_validate_with_theme_and_type(self) -> None:
        """Test validate command with both --theme and --type options."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["validate", "--theme", "buildings", "--type", "building"]
        )
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_validate_with_multiple_types(self) -> None:
        """Test validate command with multiple --type options."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["validate", "--type", "building", "--type", "place"]
        )
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_validate_with_multiple_themes(self) -> None:
        """Test validate command with multiple --theme options."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["validate", "--theme", "buildings", "--theme", "places"]
        )
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_json_schema_with_overture_types(self) -> None:
        """Test json-schema command with --overture-types option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["json-schema", "--overture-types"])
        assert result.exit_code == 0
        # Should output valid JSON
        import json

        schema = json.loads(result.output)
        assert "$defs" in schema
        assert "discriminator" in schema

    def test_json_schema_with_theme(self) -> None:
        """Test json-schema command with --theme option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["json-schema", "--theme", "buildings"])
        assert result.exit_code == 0
        # Should output valid JSON
        import json

        schema = json.loads(result.output)
        assert "$defs" in schema
        assert "Building" in str(schema)

    def test_json_schema_with_type(self) -> None:
        """Test json-schema command with --type option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["json-schema", "--type", "building"])
        assert result.exit_code == 0
        # Should output valid JSON
        import json

        schema = json.loads(result.output)
        assert "$defs" in schema
        assert "Building" in str(schema)

    def test_validate_with_nonexistent_type_shows_error(self) -> None:
        """Test validate command with nonexistent type shows error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "--type", "nonexistent"])
        assert (
            result.exit_code == 0
        )  # CLI doesn't exit with error code, just shows error message
        assert "Error: No models found matching" in result.stderr

    def test_json_schema_with_nonexistent_theme_shows_error(self) -> None:
        """Test json-schema command with nonexistent theme shows error."""
        runner = CliRunner()
        result = runner.invoke(cli, ["json-schema", "--theme", "nonexistent"])
        assert (
            result.exit_code == 0
        )  # CLI doesn't exit with error code, just shows error message
        assert "Error: No models found matching" in result.stderr

    def test_cli_help(self) -> None:
        """Test main CLI help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Overture Schema command-line interface" in result.output
        assert "validate" in result.output
        assert "json-schema" in result.output

    def test_validate_no_options_uses_all_models(self) -> None:
        """Test validate with no options uses all discovered models."""
        runner = CliRunner()
        result = runner.invoke(cli, ["validate"])
        assert result.exit_code == 0
        assert "not yet implemented" in result.output

    def test_list_types_command(self) -> None:
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

    def test_list_types_command_help(self) -> None:
        """Test list-types command help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["list-types", "--help"])
        assert result.exit_code == 0
        assert (
            "List all available types grouped by theme with descriptions"
            in result.output
        )
