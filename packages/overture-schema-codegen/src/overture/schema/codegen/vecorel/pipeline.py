"""Vecorel SDL generation pipeline: render documents without I/O.

Mirrors `json_schema/pipeline.py`, with one difference that is the point of
the arm: a model can fail to produce a document at all (a union root), so the
pipeline yields the gap log alongside whatever was emitted rather than a bare
list of files. Real SDL documents in the wild are YAML, so that is what this
writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

import yaml

from overture.schema.system.case import to_snake_case

from ..extraction.specs import ModelSpec
from .exceptions import VecorelGap
from .renderer import render_vecorel

__all__ = ["VecorelOutput", "generate_vecorel_documents"]


@dataclass(frozen=True, slots=True)
class VecorelOutput:
    """A rendered SDL document with its output path, or the reason there is none."""

    model: str
    content: str | None
    path: PurePosixPath
    gaps: tuple[VecorelGap, ...]


def _dump(document: dict) -> str:
    """Serialize to YAML in the idiom the published SDL documents use."""
    return yaml.safe_dump(document, sort_keys=False, default_flow_style=False)


def generate_vecorel_documents(
    model_specs: Sequence[ModelSpec],
) -> list[VecorelOutput]:
    """Render one Vecorel SDL document per model spec, plus its gap log."""
    outputs: list[VecorelOutput] = []
    for spec in model_specs:
        rendered = render_vecorel(spec)
        outputs.append(
            VecorelOutput(
                model=spec.name,
                content=_dump(rendered.content) if rendered.content else None,
                path=PurePosixPath(f"{to_snake_case(spec.name)}.yaml"),
                gaps=rendered.gaps,
            )
        )
    return outputs
