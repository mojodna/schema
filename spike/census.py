"""Divergence census: IR-emitted JSON Schema vs the Pydantic-derived baselines.

Spike harness for bd-jsonschema-codegen-parity-spike-k9co. Throwaway.

Walks the two documents in lockstep, resolving `$ref` on each side in its own
document so that `$defs` naming differences do not register as divergence, and
records every keyword-level difference with its JSON-pointer path.

The census is only trustworthy if the walk would report a divergence that exists,
so `--control` injects known mutations into the emitted side and asserts the
counts move. An empty column is read as parity only after the control passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Keywords whose array value is order-insensitive.
SET_VALUED = {"required", "enum"}

# Buckets, from the bead's pre-registered expectations. A keyword landing outside
# this table is an unanticipated finding and is reported as `unclassified`.
EXPECTED_BREAK = {
    "default", "examples", "example",          # defaults / examples
    "additionalProperties",                     # NoExtraFieldsConstraint
    "format",                                   # format keywords
    "required",                                 # nullable-vs-required conflation
    "alias", "serialization_alias",             # aliases
    "$comment",                                 # renderer could not map it
}
EXPECTED_WIN = {"discriminator", "$ref-identity"}
COSMETIC = {"title"}


@dataclass(frozen=True)
class Divergence:
    model: str
    path: str
    keyword: str
    kind: str          # missing | extra | value | type
    baseline: str
    emitted: str

    def bucket(self) -> str:
        if self.keyword in EXPECTED_BREAK:
            return "expected-break"
        if self.keyword in EXPECTED_WIN:
            return "expected-win"
        if self.keyword in COSMETIC:
            return "cosmetic"
        return "unclassified"


def _trunc(value: Any, n: int = 90) -> str:
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _resolve(node: Any, doc: dict[str, Any], seen: int = 0) -> Any:
    """Follow a local `$ref` chain to the node it names, within `doc`."""
    while isinstance(node, dict) and "$ref" in node and seen < 20:
        ref = node["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return node
        target: Any = doc
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return node          # dangling: leave the $ref visible
            target = target[part]
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        node = {**target, **siblings} if siblings else target
        seen += 1
    return node


class Walker:
    def __init__(self, model: str, base_doc: dict, emit_doc: dict) -> None:
        self.model = model
        self.base_doc = base_doc
        self.emit_doc = emit_doc
        self.out: list[Divergence] = []
        self._visiting: set[tuple[int, int]] = set()

    def record(self, path: str, keyword: str, kind: str, b: Any, e: Any) -> None:
        self.out.append(
            Divergence(self.model, path or "/", keyword, kind, _trunc(b), _trunc(e))
        )

    def walk(self, path: str, base: Any, emit: Any) -> None:
        base = _resolve(base, self.base_doc)
        emit = _resolve(emit, self.emit_doc)

        if isinstance(base, dict) and isinstance(emit, dict):
            key = (id(base), id(emit))
            if key in self._visiting:      # cycle: both sides recursed, stop
                return
            self._visiting.add(key)
            try:
                self._walk_dict(path, base, emit)
            finally:
                self._visiting.discard(key)
            return

        if isinstance(base, list) and isinstance(emit, list):
            self._walk_list(path, base, emit)
            return

        if type(base) is not type(emit) or base != emit:
            self.record(path, path.rsplit("/", 1)[-1] or "$root", "value", base, emit)

    def _walk_dict(self, path: str, base: dict, emit: dict) -> None:
        for k in sorted(set(base) | set(emit)):
            sub = f"{path}/{k}"
            if k not in emit:
                self.record(path or "/", k, "missing", base[k], None)
            elif k not in base:
                self.record(path or "/", k, "extra", None, emit[k])
            elif k in SET_VALUED and isinstance(base[k], list) and isinstance(emit[k], list):
                bset, eset = Counter(map(json.dumps, base[k])), Counter(map(json.dumps, emit[k]))
                if bset != eset:
                    self.record(path or "/", k, "value",
                                sorted(base[k], key=str), sorted(emit[k], key=str))
            elif k == "$defs":
                continue          # naming is by construction different; refs are followed
            else:
                self.walk(sub, base[k], emit[k])

    def _walk_list(self, path: str, base: list, emit: list) -> None:
        if len(base) != len(emit):
            self.record(path, path.rsplit("/", 1)[-1] or "$root", "value",
                        f"[{len(base)} items]", f"[{len(emit)} items]")
            return
        for i, (b, e) in enumerate(zip(base, emit)):
            self.walk(f"{path}/{i}", b, e)


UNWRAP = True   # set False with --no-unwrap to see the raw, view-inflated diff


def load_baseline(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text())
    return unwrap_geojson(doc) if UNWRAP else doc


def compare(model: str, base_path: Path, emit_path: Path) -> list[Divergence]:
    base = load_baseline(base_path)
    emit = json.loads(emit_path.read_text())
    w = Walker(model, base, emit)
    w.walk("", base, emit)
    return w.out


# --- controls -------------------------------------------------------------

def mutate(doc: Any, mode: str) -> Any:
    """Inject a known defect into an emitted document."""
    if isinstance(doc, dict):
        out = {}
        for k, v in doc.items():
            if mode == "drop-pattern" and k == "pattern":
                continue
            if mode == "drop-description" and k == "description":
                continue
            if mode == "perturb-type" and k == "type" and v == "string":
                out[k] = "integer"
                continue
            out[k] = mutate(v, mode)
        return out
    if isinstance(doc, list):
        return [mutate(v, mode) for v in doc]
    return doc



# --- the vocabulary arm ---------------------------------------------------

def _keyword_hits(node, keyword, path="", out=None):
    """Every path at which `keyword` appears."""
    if out is None:
        out = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == keyword:
                out.append(path or "/")
            _keyword_hits(v, keyword, f"{path}/{k}", out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _keyword_hits(v, keyword, f"{path}/{i}", out)
    return out


def defs_report(baselines, emitted_dir):
    """Compare the named-$defs vocabulary, which the lockstep walk erases by design.

    Resolving $ref on each side is what makes naming differences invisible to the
    divergence census -- but named $defs ARE the claimed win (NewType identity,
    union arms), so they need their own measurement rather than being inferred
    from an empty column.
    """
    print(f"{'model':22} {'base':>5} {'emit':>5} {'shared':>7} {'emit-only':>10} {'base-only':>10}  discriminator")
    for model, bpath in baselines.items():
        epath = emitted_dir / f"{model}.json"
        if not epath.exists():
            continue
        base = load_baseline(bpath)
        emit = json.loads(epath.read_text())
        bd, ed = set(base.get("$defs", {})), set(emit.get("$defs", {}))
        bdisc = len(_keyword_hits(base, "discriminator"))
        edisc = len(_keyword_hits(emit, "discriminator"))
        print(f"{model:22} {len(bd):>5} {len(ed):>5} {len(bd & ed):>7} {len(ed - bd):>10} {len(bd - ed):>10}"
              f"  base={bdisc} emit={edisc}")
        if ed - bd:
            print(f"{'':24}emit-only: {', '.join(sorted(ed - bd))}")
        if bd - ed:
            print(f"{'':24}base-only: {', '.join(sorted(bd - ed))}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--emitted", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--control", action="store_true",
                    help="run mutation controls and assert the walk reports them")
    ap.add_argument("--detail", default=None, help="print every divergence for this model")
    ap.add_argument("--no-unwrap", action="store_true",
                    help="skip GeoJSON un-enveloping (measures the view difference, not IR fidelity)")
    ap.add_argument("--defs", action="store_true", help="report the named-$defs vocabulary arm")
    args = ap.parse_args()

    global UNWRAP
    UNWRAP = not args.no_unwrap
    print(f"canonicalisation: GeoJSON envelope {'REMOVED from baselines' if UNWRAP else 'LEFT IN PLACE'}\n")

    baselines = {
        p.name[: -len("_baseline_schema.json")]: p
        for p in sorted(args.repo.glob("packages/*/tests/*_baseline_schema.json"))
    }
    if not baselines:
        print("no baselines found", file=sys.stderr)
        return 2

    all_div: list[Divergence] = []
    missing_emit: list[str] = []
    for model, bpath in baselines.items():
        epath = args.emitted / f"{model}.json"
        if not epath.exists():
            missing_emit.append(model)
            continue
        all_div.extend(compare(model, bpath, epath))

    if missing_emit:
        print(f"NO EMITTED DOCUMENT for: {', '.join(missing_emit)}\n")

    print(f"{'model':22} {'total':>6} " + " ".join(f"{b:>16}" for b in
          ("expected-break", "expected-win", "cosmetic", "unclassified")))
    per_model: dict[str, Counter] = {}
    for d in all_div:
        per_model.setdefault(d.model, Counter())[d.bucket()] += 1
    for model in baselines:
        c = per_model.get(model, Counter())
        print(f"{model:22} {sum(c.values()):>6} " + " ".join(
            f"{c[b]:>16}" for b in ("expected-break", "expected-win", "cosmetic", "unclassified")))
    print(f"{'TOTAL':22} {len(all_div):>6} " + " ".join(
        f"{sum(c[b] for c in per_model.values()):>16}"
        for b in ("expected-break", "expected-win", "cosmetic", "unclassified")))

    print("\nby keyword x kind:")
    kw = Counter((d.keyword, d.kind, d.bucket()) for d in all_div)
    for (k, kind, bucket), n in kw.most_common():
        print(f"  {n:>5}  {kind:<8} {k:<28} {bucket}")

    if args.detail:
        print(f"\ndetail for {args.detail}:")
        for d in all_div:
            if d.model == args.detail:
                print(f"  {d.kind:<8} {d.path}  [{d.keyword}]")
                print(f"      baseline: {d.baseline}")
                print(f"      emitted : {d.emitted}")

    if args.defs:
        print("\n--- named $defs vocabulary (erased by the lockstep walk, measured here) ---")
        defs_report(baselines, args.emitted)

    if args.control:
        print("\n--- controls (the walk must REPORT an injected defect) ---")
        ok = True
        for mode, keyword in (("drop-pattern", "pattern"),
                              ("drop-description", "description"),
                              ("perturb-type", "type")):
            found = 0
            for model, bpath in baselines.items():
                epath = args.emitted / f"{model}.json"
                if not epath.exists():
                    continue
                base = load_baseline(bpath)
                emit = mutate(json.loads(epath.read_text()), mode)
                w = Walker(model, base, emit)
                w.walk("", base, emit)
                baseline_n = len(compare(model, bpath, epath))
                found += len(w.out) - baseline_n
            verdict = "REPORTS" if found > 0 else "BLIND"
            ok &= found > 0
            print(f"  {mode:<18} delta={found:<6} {verdict} (keyword: {keyword})")
        print("  control verdict:", "PASS" if ok else "FAIL - do not trust an empty column")
        return 0 if ok else 1
    return 0




# --- canonicalisation: undo the GeoJSON envelope --------------------------
#
# The baselines are NOT raw `model_json_schema()` output. `Feature.__get_pydantic_
# json_schema__` (packages/overture-schema-system/.../feature.py:471) reshapes the
# flat model into a GeoJSON envelope: every field except id/bbox/geometry is moved
# down into a `properties` sub-object, a `type: {const: Feature}` is inserted, and
# `additionalProperties`/`patternProperties`/`allOf`/`if`… are migrated with it.
#
# The codegen IR models the FLAT record (the columnar view). Diffing a flat emit
# against an enveloped baseline measures the view difference, not IR fidelity, and
# would charge a 140-line presentation hook to the IR's account. So the baseline is
# un-enveloped first; what remains is the parity question the spike actually asks.

_CORE = ("id", "bbox", "geometry")


def _is_feature_envelope(node: Any) -> bool:
    props = node.get("properties") if isinstance(node, dict) else None
    if not isinstance(props, dict) or "properties" not in props:
        return False
    type_prop = props.get("type")
    return isinstance(type_prop, dict) and type_prop.get("const") == "Feature"


def unwrap_geojson(node: Any) -> Any:
    """Recursively invert the GeoJSON envelope, returning the flat-record view."""
    if isinstance(node, list):
        return [unwrap_geojson(v) for v in node]
    if not isinstance(node, dict):
        return node
    if not _is_feature_envelope(node):
        return {k: unwrap_geojson(v) for k, v in node.items()}

    top = dict(node)
    top_props = dict(top.pop("properties"))
    top_req = [r for r in top.pop("required", []) if r in _CORE]
    inner = top_props.pop("properties")
    top_props.pop("type", None)

    if isinstance(inner, dict) and "anyOf" in inner and len(inner["anyOf"]) == 2:
        # nullable properties sub-object: {"anyOf": [obj, {"type": "null"}]}
        cand = [a for a in inner["anyOf"] if a.get("type") != "null"]
        if len(cand) == 1:
            inner = cand[0]
    if not isinstance(inner, dict):
        inner = {}

    flat: dict[str, Any] = {k: v for k, v in top.items() if k not in ("additionalProperties",)}
    merged_props = {**inner.get("properties", {}), **top_props}
    if merged_props:
        flat["properties"] = merged_props
    req = list(inner.get("required", [])) + top_req
    if req:
        flat["required"] = req
    flat["type"] = "object"
    for k in ("additionalProperties", "patternProperties", "unevaluatedProperties",
              "allOf", "anyOf", "oneOf", "minProperties", "maxProperties",
              "if", "then", "else"):
        if k in inner:
            flat[k] = inner[k]
    # `not: {required: [id, bbox, geometry]}` is an artifact of the split itself:
    # it forbids the core fields INSIDE the sub-object. Flattened, it is meaningless.
    not_clause = inner.get("not")
    if not_clause is not None and not_clause != {"required": list(_CORE)}:
        flat["not"] = not_clause
    return {k: unwrap_geojson(v) for k, v in flat.items()}


if __name__ == "__main__":
    raise SystemExit(main())
