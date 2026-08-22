"""Corpus probe: what the IR actually contains, before any Vecorel emit.

Numbers here feed spike/VECOREL_PREREGISTRATION.md. Read-only.
"""
from __future__ import annotations
from collections import Counter

from overture.schema.cli.tag_options import build_selector
from overture.schema.system.discovery import discover_models, filter_models
from overture.schema.codegen.spec_discovery import extract_model_spec
from overture.schema.codegen.extraction.field import (
    AnyScalar, ArrayOf, LiteralScalar, MapOf, ModelRef, NewTypeShape, Primitive, UnionRef,
)
from overture.schema.codegen.extraction.specs import RecordSpec, UnionSpec

models = filter_models(discover_models(), build_selector((), (), ()))
specs = [s for k, e in models.items() if (s := extract_model_spec(k, e)) is not None]

base_types = Counter()
shape_kinds = Counter()
newtypes = set()
records = set()
enums = set()
fields = 0
nullable = 0
required = 0
nullable_and_required = 0
unions = 0
cycles = 0
maps = 0
anys = 0
literals = 0

seen_records: set[str] = set()

def walk_shape(sh):
    global maps, anys, literals, unions, cycles
    shape_kinds[type(sh).__name__] += 1
    match sh:
        case Primitive(base_type=bt, source_type=st):
            base_types[bt] += 1
            if st is not None and hasattr(st, "__mro__"):
                import enum as _e
                if issubclass(st, _e.Enum):
                    enums.add(st.__name__)
        case LiteralScalar():
            literals += 1
        case AnyScalar():
            anys += 1
        case ModelRef(model=m, starts_cycle=sc):
            if sc:
                cycles += 1
            else:
                walk_record(m)
        case UnionRef(union=u):
            unions += 1
            for ms in u.member_specs:
                walk_record(ms.spec)
        case ArrayOf(element=el):
            walk_shape(el)
        case MapOf(key=k, value=v):
            maps += 1
            walk_shape(k); walk_shape(v)
        case NewTypeShape(name=n, inner=inner):
            newtypes.add(n)
            walk_shape(inner)

def walk_record(rec: RecordSpec):
    global fields, nullable, required, nullable_and_required
    if rec.name in seen_records:
        return
    seen_records.add(rec.name)
    records.add(rec.name)
    for f in rec.fields:
        fields += 1
        if f.is_optional:
            nullable += 1
        if f.is_required:
            required += 1
        if f.is_optional and f.is_required:
            nullable_and_required += 1
        walk_shape(f.shape)

for s in specs:
    if isinstance(s, RecordSpec):
        walk_record(s)
    else:
        for ms in s.member_specs:
            walk_record(ms.spec)

print(f"entry points          : {len(specs)}  ({sum(1 for s in specs if isinstance(s, UnionSpec))} unions)")
print(f"reachable records     : {len(records)}")
print(f"fields                : {fields}")
print(f"  nullable            : {nullable}")
print(f"  required            : {required}")
print(f"  nullable AND req    : {nullable_and_required}")
print(f"named NewTypes        : {len(newtypes)}")
print(f"enums                 : {len(enums)}")
print(f"UnionRef sites        : {unions}")
print(f"cycle back-edges      : {cycles}")
print(f"MapOf sites           : {maps}")
print(f"AnyScalar sites       : {anys}")
print(f"LiteralScalar sites   : {literals}")
print("\nshape kinds:")
for k, v in shape_kinds.most_common():
    print(f"  {k:16s} {v}")
print("\nprimitive base_types:")
for k, v in base_types.most_common():
    print(f"  {k:16s} {v}")
