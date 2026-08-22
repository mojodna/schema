"""Bucket the census output. Run after `census.py` to reproduce the report table.

    uv run overture-codegen generate --format json-schema --output-dir <dir>
    python3 spike/classify.py <dir>
"""

import glob
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import census  # noqa: E402


def classify(d: "census.Divergence") -> str:
    k, kind, p = d.keyword, d.kind, d.path
    # Hand-written in a JSON-Schema hook, absent from the model: no extractor
    # could carry these (see CENSUS.md, "The question changed once").
    if k in ("additionalProperties", "patternProperties"):
        return "schema-only"
    # The IR has no default anywhere: dataclasses.fields(FieldSpec) is
    # (name, shape, description, is_required, is_optional).
    if k == "default":
        return "IR gap"
    # BBox is an opaque Primitive in the IR; its 4-element arity lives behind
    # the type and is not reachable. `between`'s arity IS reachable, via
    # LinearReferenceRangeConstraint, so those 44 are renderer scope.
    if k in ("minItems", "maxItems") and p.endswith("/bbox"):
        return "IR gap"
    # Python regex vs ECMA-262: the IR carries the source pattern verbatim
    # (`\Z`); JSON Schema's dialect wants `$`. A translation step, not a gap.
    if k == "pattern" and kind == "value":
        return "target dialect"
    if k == "title":
        return "cosmetic"
    if k == "discriminator":
        return "deliberate improvement"
    return "renderer scope"


def main() -> int:
    emitted = Path(sys.argv[1])
    repo = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
    div = []
    for f in sorted(repo.glob("packages/*/tests/*_baseline_schema.json")):
        name = os.path.basename(f).replace("_baseline_schema.json", "")
        div += census.compare(name, f, emitted / f"{name}.json")
    counts = Counter(classify(d) for d in div)
    total = sum(counts.values())
    print(f"{'bucket':26} {'n':>6}  {'%':>6}")
    for b, n in counts.most_common():
        print(f"{b:26} {n:>6}  {100 * n / total:>5.1f}%")
    print(f"{'TOTAL':26} {total:>6}")
    for bucket in ("IR gap", "renderer scope"):
        print(f"\n{bucket}:")
        for (k, kind), n in Counter(
            (d.keyword, d.kind) for d in div if classify(d) == bucket
        ).most_common(10):
            print(f"   {n:>4}  {kind:<8} {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
