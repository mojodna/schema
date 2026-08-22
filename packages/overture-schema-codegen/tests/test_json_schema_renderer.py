"""Acceptance tests for the JSON Schema spike renderer.

Covers acceptance criteria 1 and 2 from `spike/RENDERER_SPEC.md`: the CLI
writes one document per baseline feature type without raising, and every
emitted document parses as JSON with every `$ref` resolving within its own
document. This is the only test the spike calls for -- it deliberately does
not compare output against the golden baselines (that comparison is the
separate, out-of-repo census; see `spike/RENDERER_SPEC.md` for why fitting
the renderer toward the baselines would make the census meaningless).
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from overture.schema.codegen.cli import cli

_EXPECTED_NAMES = {
    "address",
    "bathymetry",
    "infrastructure",
    "land",
    "land_cover",
    "land_use",
    "water",
    "building",
    "building_part",
    "division",
    "division_area",
    "division_boundary",
    "place",
    "connector",
    "segment",
}


def _collect_refs(node: object, refs: list[str]) -> None:
    """Collect every `$ref` string reachable from *node*, recursively."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            refs.append(ref)
        for value in node.values():
            _collect_refs(value, refs)
    elif isinstance(node, list):
        for item in node:
            _collect_refs(item, refs)


class TestJsonSchemaGenerate:
    """generate --format json-schema, per spike/RENDERER_SPEC.md acceptance criteria."""

    def test_writes_one_file_per_baseline_feature_type(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Criterion 1: 15 files, one per baseline feature type, no raise."""
        result = cli_runner.invoke(
            cli,
            ["generate", "--format", "json-schema", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output

        json_files = sorted(tmp_path.glob("*.json"))
        names = {f.stem for f in json_files}
        assert names == _EXPECTED_NAMES

    def test_every_document_parses_and_refs_resolve(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Criterion 2: every document is valid JSON; every $ref resolves in-document."""
        result = cli_runner.invoke(
            cli,
            ["generate", "--format", "json-schema", "--output-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output

        json_files = sorted(tmp_path.glob("*.json"))
        assert json_files, "expected json-schema output files"

        for path in json_files:
            document = json.loads(path.read_text())
            defs = document.get("$defs", {})
            refs: list[str] = []
            _collect_refs(document, refs)
            for ref in refs:
                assert ref.startswith("#/$defs/"), (
                    f"{path.name}: unexpected $ref form {ref!r}"
                )
                name = ref.removeprefix("#/$defs/")
                assert name in defs, f"{path.name}: dangling $ref {ref!r}"
