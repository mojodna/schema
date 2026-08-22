"""What the emitted SDL documents actually contain, by keyword and type.

Counts sites in the emitted documents -- the complement of the gap log, which
counts what did not survive. Both are needed: a gap column is only readable
next to the population it was drawn from.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

# Keys under `properties` / `patternProperties` are property NAMES, not SDL
# keywords; counting them conflated the schema vocabulary with the data model.
_NAME_MAPS = ("properties", "patternProperties")


def walk(node, kw: Counter, types: Counter, geom: Counter):
    if isinstance(node, dict):
        for k, v in node.items():
            kw[k] += 1
            if k == "type" and isinstance(v, str):
                types[v] += 1
            if k == "geometryTypes" and isinstance(v, list):
                for g in v:
                    geom[g] += 1
            if k in _NAME_MAPS and isinstance(v, dict):
                for sub in v.values():
                    walk(sub, kw, types, geom)
            elif k not in ("enum", "geometryTypes", "required"):
                walk(v, kw, types, geom)
    elif isinstance(node, list):
        for v in node:
            walk(v, kw, types, geom)

def main() -> int:
    d = Path(sys.argv[1])
    kw, types, geom = Counter(), Counter(), Counter()
    docs = sorted(d.glob("*.yaml"))
    for path in docs:
        walk(yaml.safe_load(path.read_text()), kw, types, geom)
    print(f"documents: {len(docs)}\n")
    print("vecorel types emitted:")
    for k, v in types.most_common():
        print(f"  {k:<14}{v:>5}")
    print("\nkeywords emitted:")
    for k, v in kw.most_common():
        print(f"  {k:<22}{v:>5}")
    print("\ngeometryTypes members:")
    for k, v in geom.most_common():
        print(f"  {k:<18}{v:>5}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
