"""Validate emitted SDL documents against the Vecorel metaschema.

Ground truth for *validity* is the metaschema, not the renderer's author. The
`--control` arm mutates each document and asserts validation FAILS: a pass
means nothing until the validator is shown to be capable of reporting.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

HERE = Path(__file__).parent
METASCHEMA = json.loads((HERE / "vecorel-sdl-metaschema.json").read_text())


def errors_for(doc: dict) -> list[str]:
    v = Draft202012Validator(METASCHEMA)
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '/'}: {e.message}"
        for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))
    ]


def _first_prop(doc: dict, fn) -> None:
    for value in (doc.get("properties") or {}).values():
        if isinstance(value, dict):
            fn(value)
            return


MUTATIONS = {
    # `type` is required on every subschema.
    "drop-type": lambda d: _first_prop(d, lambda p: p.pop("type", None)),
    # A type name outside the closed enum.
    "bad-type": lambda d: _first_prop(d, lambda p: p.__setitem__("type", "varchar")),
    # The `^$` patternProperties defect: a top-level $id should be REJECTED.
    "top-level-id": lambda d: d.__setitem__("$id", "https://example.com/x.yaml"),
    # An unknown root key, which additionalProperties:false must catch.
    "root-extra": lambda d: d.__setitem__("titel", "typo"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", type=Path)
    ap.add_argument("--control", action="store_true")
    args = ap.parse_args()

    docs = sorted(args.directory.glob("*.yaml"))
    if not docs:
        print("no documents found -- refusing to report a pass", file=sys.stderr)
        return 2

    if args.control:
        print(f"CONTROL: {len(MUTATIONS)} mutations x {len(docs)} documents")
        ok = True
        for name, mutate in MUTATIONS.items():
            caught = 0
            for path in docs:
                doc = copy.deepcopy(yaml.safe_load(path.read_text()))
                mutate(doc)
                if errors_for(doc):
                    caught += 1
            verdict = "REPORTS" if caught == len(docs) else "BLIND"
            print(f"  {name:14s} caught {caught}/{len(docs)}  {verdict}")
            ok = ok and caught == len(docs)
        print("  control " + ("PASS" if ok else "FAIL"))
        return 0 if ok else 1

    failures = 0
    for path in docs:
        errs = errors_for(yaml.safe_load(path.read_text()))
        if errs:
            failures += 1
            print(f"FAIL {path.name}  ({len(errs)} errors)")
            for e in errs[:6]:
                print(f"     {e}")
            if len(errs) > 6:
                print(f"     ... {len(errs) - 6} more")
        else:
            print(f"ok   {path.name}")
    print(f"\n{len(docs) - failures}/{len(docs)} valid against the SDL metaschema")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
