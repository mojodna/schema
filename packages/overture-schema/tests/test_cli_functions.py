"""Tests for CLI helper functions (load_input, perform_validation)."""

from pathlib import Path

import pytest
import yaml
from click.exceptions import UsageError
from overture.schema.cli.commands import load_input, perform_validation, resolve_types
from pydantic import ValidationError


class TestLoadInput:
    """Tests for load_input function.

    Note: Happy-path file and stdin loading are covered by integration tests
    in test_cli_commands.py. These tests focus on error cases and edge cases.
    """

    def test_load_input_file_not_found(self) -> None:
        """Test that load_input raises UsageError when file doesn't exist."""

        with pytest.raises(UsageError) as exc_info:
            load_input(Path("/nonexistent/path/to/file.yaml"))

        assert "is not a file" in str(exc_info.value)

    def test_load_input_path_is_directory(
        self, cli_runner: pytest.FixtureRequest
    ) -> None:
        """Test that load_input raises UsageError when path is a directory.

        Note: cli_runner provides isolated filesystem for test file creation.
        """

        # Create a directory
        Path("testdir").mkdir()

        with pytest.raises(UsageError) as exc_info:
            load_input(Path("testdir"))

        assert "is not a file" in str(exc_info.value)

    def test_load_input_invalid_yaml(self, cli_runner: pytest.FixtureRequest) -> None:
        """Test that load_input raises YAMLError for invalid YAML.

        Note: cli_runner provides isolated filesystem for test file creation.
        """
        invalid_yaml = "test.yaml"
        with open(invalid_yaml, "w") as f:
            f.write("invalid: yaml: content: [")

        with pytest.raises(yaml.YAMLError):
            load_input(Path(invalid_yaml))

    def test_load_input_handles_json(self, cli_runner: pytest.FixtureRequest) -> None:
        """Test that load_input can parse JSON files.

        Note: cli_runner provides isolated filesystem for test file creation.
        """
        json_file = "test.json"
        with open(json_file, "w") as f:
            f.write(
                '{"id": "test", "type": "Feature", "properties": {"type": "building"}}'
            )

        data, source_name = load_input(Path(json_file))

        assert isinstance(data, dict)
        assert data["id"] == "test"
        assert source_name == json_file

    def test_load_input_handles_list(self, cli_runner: pytest.FixtureRequest) -> None:
        """Test that load_input can parse YAML lists.

        Note: cli_runner provides isolated filesystem for test file creation.
        """
        list_file = "list.yaml"
        with open(list_file, "w") as f:
            f.write("""
- id: test1
  type: Feature
- id: test2
  type: Feature
""")

        data, source_name = load_input(Path(list_file))

        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["id"] == "test1"

    @pytest.mark.parametrize(
        "extension",
        [".txt", ".csv", ".xml", ".data", ""],
    )
    def test_load_input_warns_unexpected_extension(
        self,
        cli_runner: pytest.FixtureRequest,
        capsys: pytest.CaptureFixture,
        extension: str,
    ) -> None:
        """Test that load_input warns about unexpected file extensions.

        Note: cli_runner provides isolated filesystem for test file creation.
        """
        filename = f"data{extension}"
        with open(filename, "w") as f:
            f.write(
                '{"id": "test", "type": "Feature", "properties": {"type": "building"}}'
            )

        load_input(Path(filename))

        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "unexpected extension" in captured.err
        assert filename in captured.err

    @pytest.mark.parametrize(
        "extension",
        [".json", ".yaml", ".yml", ".geojson"],
    )
    def test_load_input_no_warning_expected_extension(
        self,
        cli_runner: pytest.FixtureRequest,
        capsys: pytest.CaptureFixture,
        extension: str,
    ) -> None:
        """Test that load_input does not warn for expected file extensions.

        Note: cli_runner provides isolated filesystem for test file creation.
        """
        filename = f"data{extension}"
        with open(filename, "w") as f:
            f.write(
                '{"id": "test", "type": "Feature", "properties": {"type": "building"}}'
            )

        load_input(Path(filename))

        captured = capsys.readouterr()
        assert captured.err == ""


class TestPerformValidation:
    """Tests for perform_validation function.

    Note: Happy-path validation (single features, lists, FeatureCollections, flat format)
    is covered by integration tests in test_cli_commands.py. These tests focus on edge
    cases and validation logic specific to the function.
    """

    @pytest.mark.parametrize(
        "data,expected_in_loc",
        [
            # Single invalid feature - missing 'id'
            (
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                    },
                    "properties": {
                        "theme": "buildings",
                        "type": "building",
                        "version": 0,
                    },
                },
                "id",
            ),
            # List with invalid item at index 1 - missing 'id'
            (
                [
                    {
                        "id": "test1",
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
                        },
                        "properties": {
                            "theme": "buildings",
                            "type": "building",
                            "version": 0,
                        },
                    },
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3], [2, 2]]],
                        },
                        "properties": {
                            "theme": "buildings",
                            "type": "building",
                            "version": 0,
                        },
                    },
                ],
                1,  # List index where error occurs
            ),
        ],
    )
    def test_perform_validation_raises_for_invalid_data(
        self, data: dict | list, expected_in_loc: str | int
    ) -> None:
        """Test that perform_validation raises ValidationError with proper error location."""
        model_type = resolve_types(False, None, ("buildings",), ())

        with pytest.raises(ValidationError) as exc_info:
            perform_validation(data, model_type)

        errors = exc_info.value.errors()
        assert any(expected_in_loc in error.get("loc", ()) for error in errors)

    def test_perform_validation_empty_list(self) -> None:
        """Test validating an empty list (edge case)."""
        data: list[dict[str, object]] = []
        model_type = resolve_types(False, None, ("buildings",), ())

        # Should not raise
        perform_validation(data, model_type)

    def test_perform_validation_empty_feature_collection(self) -> None:
        """Test validating an empty FeatureCollection (edge case)."""
        data = {"type": "FeatureCollection", "features": []}
        model_type = resolve_types(False, None, ("buildings",), ())

        # Should not raise
        perform_validation(data, model_type)

    def test_perform_validation_with_different_themes(self) -> None:
        """Test validating features from different themes."""
        data = {
            "id": "test",
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            },
            "properties": {"theme": "buildings", "type": "building", "version": 0},
        }

        # Should work with buildings theme
        buildings_type = resolve_types(False, None, ("buildings",), ())
        perform_validation(data, buildings_type)

        # Should fail with wrong theme
        places_type = resolve_types(False, None, ("places",), ())
        with pytest.raises(ValidationError):
            perform_validation(data, places_type)
