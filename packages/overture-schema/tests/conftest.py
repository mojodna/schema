"""Shared test fixtures for CLI tests."""

from collections.abc import Generator
from io import StringIO
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from rich.console import Console


@pytest.fixture
def cli_runner() -> Generator[CliRunner, None, None]:
    """Provide a CliRunner within an isolated filesystem."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        yield runner


@pytest.fixture
def stderr_buffer() -> Generator[StringIO, None, None]:
    """Provide a patched stderr buffer for capturing CLI error output."""
    buffer = StringIO()
    captured_console = Console(file=buffer, force_terminal=False)

    with patch("overture.schema.cli.commands.stderr", captured_console):
        yield buffer


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
