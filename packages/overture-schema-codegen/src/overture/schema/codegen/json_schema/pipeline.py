"""JSON Schema generation pipeline: render documents without I/O.

Mirrors the shape of `markdown/pipeline.py` and `pyspark/pipeline.py`:
produce a list of rendered outputs, and let the caller (`cli.py`) decide
what to do with them (write to disk, stream to stdout).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

from overture.schema.system.case import to_snake_case

from ..extraction.specs import ModelSpec
from .renderer import render_json_schema

__all__ = ["JsonSchemaDocument", "generate_json_schema_documents"]


@dataclass(frozen=True, slots=True)
class JsonSchemaDocument:
    """A rendered JSON Schema document with its content and output path."""

    content: str
    path: PurePosixPath


def generate_json_schema_documents(
    model_specs: Sequence[ModelSpec],
) -> list[JsonSchemaDocument]:
    """Render one self-contained JSON Schema document per model spec.

    Each document's `$defs` holds every record, enum, and NewType that
    spec's fields reach; every `$ref` resolves within that same document,
    so documents don't reference each other's `$defs`.
    """
    documents: list[JsonSchemaDocument] = []
    for spec in model_specs:
        schema = render_json_schema(spec)
        content = json.dumps(schema, indent=2, sort_keys=True) + "\n"
        path = PurePosixPath(f"{to_snake_case(spec.name)}.json")
        documents.append(JsonSchemaDocument(content=content, path=path))
    return documents
