"""Render a `ModelSpec` to a JSON Schema document, from the codegen IR alone.

Spike-quality: this renderer exists to measure where an IR-driven emit
diverges from the Pydantic-derived baseline schemas
(`packages/*/tests/*_baseline_schema.json`), not to match them. See
`spike/RENDERER_SPEC.md` for the mapping rules this module follows, and
`spike/RENDERER_NOTES.md` for judgment calls made along the way.

Every unmapped base type or constraint becomes an explicit `$comment`
marker rather than a silent omission, so a later census can count what
this renderer did not carry.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from annotated_types import Ge, Gt, Interval, Le, Lt, MultipleOf
from pydantic import BaseModel
from typing_extensions import assert_never

from overture.schema.system.geometric import GeometryTypeConstraint
from overture.schema.system.model_constraint import NoExtraFieldsConstraint

from ..extraction.enum_extraction import extract_enum
from ..extraction.field import (
    AnyScalar,
    ArrayOf,
    ConstraintSource,
    FieldShape,
    LiteralScalar,
    MapOf,
    ModelRef,
    NewTypeShape,
    Primitive,
    UnionRef,
)
from ..extraction.field_walk import all_constraints
from ..extraction.length_constraints import (
    ArrayMaxLen,
    ArrayMinLen,
    ScalarMaxLen,
    ScalarMinLen,
)
from ..extraction.model_extraction import extract_model
from ..extraction.specs import FieldSpec, ModelSpec, RecordSpec, UnionSpec

__all__ = ["render_json_schema"]


# Explicit JSON Schema mapping for the codegen's primitive base-type names.
# Deliberately hardcoded from the spec's table rather than derived from
# `type_registry.PRIMITIVE_TYPES` (which encodes markdown/spark targets, not
# JSON Schema keywords) -- keeps this renderer's mapping legible on its own.
# Fallback keyed on the underlying Python type rather than the codegen name.
# Order matters: `bool` is a subclass of `int`, so it must be tested first.
_BUILTIN_JSON_TYPES: tuple[tuple[type, dict[str, Any]], ...] = (
    (bool, {"type": "boolean"}),
    (_dt.datetime, {"type": "string", "format": "date-time"}),
    (_dt.date, {"type": "string", "format": "date"}),
    (str, {"type": "string"}),
    (int, {"type": "integer"}),
    (float, {"type": "number"}),
)


_PRIMITIVE_JSON_TYPES: dict[str, dict[str, Any]] = {
    "int8": {"type": "integer"},
    "int16": {"type": "integer"},
    "int32": {"type": "integer"},
    "int64": {"type": "integer"},
    "uint8": {"type": "integer"},
    "uint16": {"type": "integer"},
    "uint32": {"type": "integer"},
    "int": {"type": "integer"},
    "float32": {"type": "number"},
    "float64": {"type": "number"},
    "float": {"type": "number"},
    "str": {"type": "string"},
    "bool": {"type": "boolean"},
    "Geometry": {"type": "object"},
    "BBox": {"type": "array", "items": {"type": "number"}},
}


@dataclass
class _RenderCtx:
    """Mutable render state: the `$defs` accumulated so far.

    A name is reserved with a placeholder before recursing into its body,
    so a cycle back-edge (`ModelRef.starts_cycle`) that lands on a name
    already being rendered returns the `$ref` without re-entering it.
    """

    defs: dict[str, dict[str, Any]] = field(default_factory=dict)


def render_json_schema(spec: ModelSpec) -> dict[str, Any]:
    """Render *spec* to a JSON Schema document using only the codegen IR.

    The document is the model's own schema (an object schema for a
    `RecordSpec`, a `oneOf` schema for a `UnionSpec`) plus a `$defs` object
    holding every record, enum, and NewType the model's fields reach,
    keyed by IR name. `$defs` is omitted when nothing was collected.
    """
    ctx = _RenderCtx()
    match spec:
        case RecordSpec():
            document = _render_record_body(spec, ctx)
        case UnionSpec():
            document = _render_union_body(spec, ctx)
        case _:
            assert_never(spec)
    if ctx.defs:
        document["$defs"] = ctx.defs
    return document


def _field_title(name: str) -> str:
    """Title-case a field name for display, matching Pydantic's convention.

    >>> _field_title("record_id")
    'Record Id'
    """
    return name.replace("_", " ").title()


def _set_comment(schema: dict[str, Any], comments: list[str]) -> None:
    """Attach accumulated `$comment` text to *schema*, if any was collected."""
    if not comments:
        return
    schema["$comment"] = comments[0] if len(comments) == 1 else "; ".join(comments)


def _json_literal(value: object) -> str | int | float | bool | None:
    """Coerce a `Literal[...]` value to something `json.dumps` can encode."""
    if isinstance(value, Enum):
        result = value.value
        assert isinstance(result, (str, int, float, bool)) or result is None
        return result
    assert isinstance(value, (str, int, float, bool)) or value is None
    return value


def _render_record_body(record: RecordSpec, ctx: _RenderCtx) -> dict[str, Any]:
    """Render a `RecordSpec` as a JSON Schema object schema.

    Used both for the root document (when the top-level spec is a
    `RecordSpec`) and for a `$defs` entry (when reached via `ModelRef` or
    as a union member).
    """
    schema: dict[str, Any] = {"type": "object", "title": record.name}
    if record.description is not None:
        schema["description"] = record.description

    properties: dict[str, Any] = {}
    required: list[str] = []
    for f in record.fields:
        properties[f.name] = _render_field(f, ctx)
        if f.is_required:
            required.append(f.name)
    schema["properties"] = properties
    if required:
        schema["required"] = required

    if any(isinstance(c, NoExtraFieldsConstraint) for c in record.constraints):
        schema["additionalProperties"] = False

    return schema


def _render_field(f: FieldSpec, ctx: _RenderCtx) -> dict[str, Any]:
    """Render one field's schema, wrapped with its description/title."""
    schema = _shape_to_schema(f.shape, ctx)
    if f.description is not None:
        schema["description"] = f.description
    schema["title"] = _field_title(f.name)
    return schema


def _render_union_body(union: UnionSpec, ctx: _RenderCtx) -> dict[str, Any]:
    """Render a `UnionSpec` as a JSON Schema `oneOf` schema.

    Used both for the root document (when the top-level spec is a
    `UnionSpec`) and inline wherever a `UnionRef` is encountered in a
    field's shape -- the union itself is never placed in `$defs`, only
    its members are.
    """
    schema: dict[str, Any] = {"title": union.name}
    if union.description is not None:
        schema["description"] = union.description

    one_of: list[dict[str, Any]] = []
    for member in union.member_specs:
        one_of.append(
            _register_record(member.spec, ctx, key=member.member_cls.__name__)
        )
    schema["oneOf"] = one_of

    if union.discriminator_field is not None:
        mapping = {
            tag: f"#/$defs/{member_cls.__name__}"
            for tag, member_cls in (union.discriminator_mapping or {}).items()
        }
        schema["discriminator"] = {
            "propertyName": union.discriminator_field,
            "mapping": mapping,
        }

    return schema


def _register_record(
    model: RecordSpec, ctx: _RenderCtx, *, key: str | None = None
) -> dict[str, Any]:
    """Ensure *model* has a `$defs` entry, returning a `$ref` to it.

    *key* overrides the `$defs` name (used for union members, which are
    keyed by class `__name__` rather than `RecordSpec.name`). A name
    already present in `ctx.defs` -- including a placeholder reserved by
    an in-progress render -- short-circuits without recursing again, which
    is what stops a `ModelRef` cycle back-edge from looping forever.
    """
    name = key if key is not None else model.name
    ref = {"$ref": f"#/$defs/{name}"}
    if name in ctx.defs:
        return ref
    ctx.defs[name] = {}
    ctx.defs[name] = _render_record_body(model, ctx)
    return ref


def _register_model_by_class(cls: type[BaseModel], ctx: _RenderCtx) -> dict[str, Any]:
    """Register a `$defs` entry for a `BaseModel` class with no `RecordSpec`.

    Reached only when a `Primitive.source_type` is a `BaseModel` subclass
    that extraction left unresolved (no `model_resolver` supplied, so no
    `ModelRef` was produced). `extract_model` is a public extraction
    entrypoint; calling it here materializes the `RecordSpec` this
    renderer needs without touching extraction itself.
    """
    name = cls.__name__
    ref = {"$ref": f"#/$defs/{name}"}
    if name in ctx.defs:
        return ref
    ctx.defs[name] = {}
    ctx.defs[name] = _render_record_body(extract_model(cls), ctx)
    return ref


def _register_enum(enum_cls: type[Enum], ctx: _RenderCtx) -> dict[str, Any]:
    """Ensure an enum class has a `$defs` entry, returning a `$ref` to it."""
    name = enum_cls.__name__
    ref = {"$ref": f"#/$defs/{name}"}
    if name in ctx.defs:
        return ref
    enum_spec = extract_enum(enum_cls)
    schema: dict[str, Any] = {
        "type": "string",
        "enum": [m.value for m in enum_spec.members],
        "title": enum_spec.name,
    }
    if enum_spec.description is not None:
        schema["description"] = enum_spec.description
    ctx.defs[name] = schema
    return ref


def _register_newtype(name: str, inner: FieldShape, ctx: _RenderCtx) -> dict[str, Any]:
    """Ensure a NewType has a `$defs` entry holding its inner shape's schema.

    Deliberately not inlined -- see `NewTypeShape` in `spike/RENDERER_SPEC.md`.
    No title/description is added to the entry itself (the spec's mapping
    table doesn't call for it here, unlike the enum entry above); see
    `spike/RENDERER_NOTES.md`.
    """
    ref = {"$ref": f"#/$defs/{name}"}
    if name in ctx.defs and not ctx.defs[name]:
        return ref  # cycle back-edge: the entry is being built
    rendered = _shape_to_schema(inner, ctx)
    if name not in ctx.defs:
        ctx.defs[name] = {}  # placeholder, so a cycle terminates
        ctx.defs[name] = rendered
        return ref
    if ctx.defs[name] == rendered:
        return ref
    # Two uses of the SAME NewType rendered differently, because constraints
    # attach at the USE SITE (the ConstraintSource chain) rather than to the
    # NewType. Sharing one `$def` would leak the first use's bounds onto every
    # other -- measured: VehicleAxleCountSelector's `le=100`/`multipleOf=1`
    # landed on height, length, weight and width. Inline this use instead: the
    # named-`$def` win is real only where the schema really is shared.
    return rendered


def _primitive_schema(
    base_type: str, source_type: type | None, ctx: _RenderCtx
) -> dict[str, Any]:
    """Render a `Primitive`'s base schema (before constraints are merged in)."""
    mapping = _PRIMITIVE_JSON_TYPES.get(base_type)
    if mapping is not None:
        return dict(mapping)
    if isinstance(source_type, type):
        if issubclass(source_type, Enum):
            return _register_enum(source_type, ctx)
        if issubclass(source_type, BaseModel):
            return _register_model_by_class(source_type, ctx)
        # The registry keys on the codegen base-type NAME, which has no entry for
        # the repo's constrained-string NewTypes (StrippedString, LanguageTag,
        # CountryCodeAlpha2...). The IR still carries the underlying Python type
        # on `Primitive.source_type` -- literally `<class 'str'>` -- so falling
        # back to it recovers the JSON type without widening the registry.
        for py_type, mapped in _BUILTIN_JSON_TYPES:
            if issubclass(source_type, py_type):
                return dict(mapped)
    return {"$comment": f"unmapped: {base_type}"}


def _find_pattern(shape: FieldShape) -> str | None:
    """Return the first compiled-regex pattern source found on *shape*, if any."""
    for cs in all_constraints(shape):
        compiled = getattr(cs.constraint, "pattern", None)
        if isinstance(compiled, re.Pattern):
            source = compiled.pattern
            assert isinstance(source, str)
            return source
    return None


def _merge_constraints(
    schema: dict[str, Any], constraints: tuple[ConstraintSource, ...]
) -> None:
    """Merge each constraint's keyword into *schema*, in place.

    Unmapped constraints accumulate into `$comment` rather than being
    dropped -- see the constraint table in `spike/RENDERER_SPEC.md`.
    """
    comments: list[str] = []
    for cs in constraints:
        c = cs.constraint
        if isinstance(c, Interval):
            if c.ge is not None:
                schema["minimum"] = c.ge
            if c.gt is not None:
                schema["exclusiveMinimum"] = c.gt
            if c.le is not None:
                schema["maximum"] = c.le
            if c.lt is not None:
                schema["exclusiveMaximum"] = c.lt
        elif isinstance(c, Ge):
            schema["minimum"] = c.ge
        elif isinstance(c, Gt):
            schema["exclusiveMinimum"] = c.gt
        elif isinstance(c, Le):
            schema["maximum"] = c.le
        elif isinstance(c, Lt):
            schema["exclusiveMaximum"] = c.lt
        elif isinstance(c, MultipleOf):
            schema["multipleOf"] = c.multiple_of
        elif isinstance(c, ScalarMinLen):
            schema["minLength"] = c.min_length
        elif isinstance(c, ScalarMaxLen):
            schema["maxLength"] = c.max_length
        elif isinstance(c, ArrayMinLen):
            schema["minItems"] = c.min_length
        elif isinstance(c, ArrayMaxLen):
            schema["maxItems"] = c.max_length
        elif type(c).__name__ == "UniqueItemsConstraint":
            schema["uniqueItems"] = True
        elif isinstance(compiled_pattern := getattr(c, "pattern", None), re.Pattern):
            schema["pattern"] = compiled_pattern.pattern
            # A custom constraint class may carry length bounds alongside its
            # regex (NoWhitespaceString, SnakeCaseString...); the IR keeps them
            # on the same object, so read them rather than dropping to a comment.
            min_len = getattr(c, "min_length", None)
            if isinstance(min_len, int):
                schema["minLength"] = min_len
            max_len = getattr(c, "max_length", None)
            if isinstance(max_len, int):
                schema["maxLength"] = max_len
        elif isinstance(c, GeometryTypeConstraint):
            labels = ", ".join(gt.value for gt in c.allowed_types)
            comments.append(f"geometry types: {labels}")
        else:
            comments.append(f"unmapped constraint: {type(c).__name__}")
    _set_comment(schema, comments)


def _shape_to_schema(shape: FieldShape, ctx: _RenderCtx) -> dict[str, Any]:
    """Render one `FieldShape` layer (and its descendants) to a JSON Schema."""
    match shape:
        case Primitive(base_type=base_type, source_type=source_type, constraints=cs):
            schema = _primitive_schema(base_type, source_type, ctx)
            _merge_constraints(schema, cs)
            return schema
        case LiteralScalar(values=values, constraints=cs):
            literal_schema: dict[str, Any]
            if len(values) == 1:
                literal_schema = {"const": _json_literal(values[0])}
            else:
                literal_schema = {"enum": [_json_literal(v) for v in values]}
            _merge_constraints(literal_schema, cs)
            return literal_schema
        case AnyScalar(constraints=cs):
            any_schema: dict[str, Any] = {}
            _merge_constraints(any_schema, cs)
            return any_schema
        case ModelRef(model=model):
            return _register_record(model, ctx)
        case UnionRef(union=union):
            return _render_union_body(union, ctx)
        case ArrayOf(element=element, constraints=cs):
            array_schema: dict[str, Any] = {
                "type": "array",
                "items": _shape_to_schema(element, ctx),
            }
            _merge_constraints(array_schema, cs)
            return array_schema
        case MapOf(key=key, value=value, constraints=cs):
            map_schema: dict[str, Any] = {
                "type": "object",
                "additionalProperties": _shape_to_schema(value, ctx),
            }
            pattern = _find_pattern(key)
            if pattern is not None:
                map_schema["propertyNames"] = {"pattern": pattern}
            _merge_constraints(map_schema, cs)
            return map_schema
        case NewTypeShape(name=name, inner=inner):
            return _register_newtype(name, inner, ctx)
        case _:
            assert_never(shape)
