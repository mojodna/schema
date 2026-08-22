"""Vecorel SDL coverage-and-exception census.

There is no baseline emitter for this target, so this is not a divergence diff
(the JSON Schema arm's method) but a coverage census: emit every model,
aggregate the gap log by mechanism, and report.

`--control` runs C1-C3 from spike/VECOREL_PREREGISTRATION.md against synthetic
models that deliberately contain what the corpus does not, so that a zero in
any exception column is a statement about the corpus rather than about a
renderer that would never have reported.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field

from overture.schema.cli.tag_options import build_selector
from overture.schema.codegen.extraction.model_extraction import extract_model
from overture.schema.codegen.spec_discovery import extract_model_spec
from overture.schema.codegen.vecorel.renderer import render_vecorel
from overture.schema.system.discovery import discover_models, filter_models


def corpus():
    models = filter_models(discover_models(), build_selector((), (), ()))
    return [s for k, e in models.items() if (s := extract_model_spec(k, e)) is not None]


def census() -> int:
    specs = corpus()
    by_kind: Counter[str] = Counter()
    by_capability: Counter[tuple[str, str]] = Counter()
    emitted = 0
    per_model: list[tuple[str, int, int]] = []

    for spec in specs:
        doc = render_vecorel(spec)
        if doc.emitted:
            emitted += 1
        for g in doc.gaps:
            by_kind[g.kind] += 1
            by_capability[(g.kind, g.capability)] += 1
        per_model.append((spec.name, len(doc.gaps), int(doc.emitted)))

    total = sum(by_kind.values())
    print(f"models: {len(specs)}   documents emitted: {emitted}/{len(specs)}")
    print(f"gaps:   {total}\n")

    print(f"{'kind':<16}{'n':>7}{'%':>8}")
    for kind, n in by_kind.most_common():
        print(f"{kind:<16}{n:>7}{100 * n / total:>7.1f}%")

    print(f"\n{'kind':<16}{'capability':<34}{'n':>6}")
    for (kind, cap), n in by_capability.most_common():
        print(f"{kind:<16}{cap:<34}{n:>6}")

    print(f"\n{'model':<24}{'gaps':>6}{'doc':>6}")
    for name, n, ok in sorted(per_model, key=lambda r: -r[1]):
        print(f"{name:<24}{n:>6}{'yes' if ok else 'NO':>6}")
    return 0


# --- controls -------------------------------------------------------------


class BareInt(BaseModel):
    """C1: a numeric with no declared storage width."""

    x: int
    y: float


class RequiredNullable(BaseModel):
    """C2: a field that is both nullable and required -- 0 of 394 in the corpus."""

    x: Optional[str] = Field(...)


class Node(BaseModel):
    """C3: self-referential, which SDL cannot express at any depth."""

    name: str
    child: Optional["Node"] = None


class HasMultipleOf(BaseModel):
    """C-extra: multipleOf, to prove the target-gap path fires on demand."""

    n: Annotated[int, Field(multiple_of=2)]


class HasAny(BaseModel):
    """C-extra: an untyped value."""

    blob: Any = None


Node.model_rebuild()

CONTROLS: list[tuple[str, type[BaseModel], str, str]] = [
    ("C1 bare int/float", BareInt, "ir-gap", "numeric width"),
    ("C2 required+nullable", RequiredNullable, "target-gap", "nullable"),
    ("C3 recursion", Node, "target-gap", "recursion"),
    ("C4 multipleOf", HasMultipleOf, "target-gap", "multipleOf"),
    ("C5 Any", HasAny, "target-gap", "Any"),
]


def controls() -> int:
    print("CONTROLS -- each asserts a NON-EMPTY expected result on the same")
    print("instrument that reports the corpus columns.\n")
    ok = True
    for label, model, kind, capability in CONTROLS:
        try:
            doc = render_vecorel(extract_model(model))
            gaps = doc.gaps
        except Exception as exc:  # recursion raises rather than returning
            gaps = getattr(exc, "gaps", ())
        hits = [g for g in gaps if g.kind == kind and g.capability == capability]
        verdict = "REPORTS" if hits else "BLIND"
        ok = ok and bool(hits)
        print(f"  {label:<24}{kind}/{capability:<26}{len(hits):>3}  {verdict}")
        if hits:
            print(f"      {hits[0].detail}")
    print("\n  control " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--control", action="store_true")
    args = ap.parse_args()
    return controls() if args.control else census()


if __name__ == "__main__":
    sys.exit(main())
