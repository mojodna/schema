"""Render a `ModelSpec` to a Vecorel SDL document, from the codegen IR alone.

Spike-quality, and the deliverable is the exception census rather than the
document: emit Vecorel SDL from `ModelSpec` / `FieldShape` alone, so what it
cannot say measures the gap -- in both directions. See
`spike/VECOREL_PREREGISTRATION.md` for what was predicted before any emit.

Vecorel SDL (https://vecorel.org/sdl/v0.2.0/schema.json) is a flat, fully
inlined vocabulary: no `$defs`, no `$ref`, no union, and a closed set of
physical types. Three structural consequences drive this renderer.

* Every nesting inlines. Named records, NewTypes and enums lose their names,
  and a cycle would not terminate -- so a cycle back-edge raises.
* The document root permits only `$schema`, `required`, `collection` and
  `properties` (`additionalProperties: false`), so a model's own description
  has nowhere to live.
* `nullable` does not exist. Vecorel *defines* nullability as the complement
  of `required`, so the emit cannot lose the distinction -- it is obliged to
  collapse it, which changes the meaning of a field that is optional-with-a-
  default but not `None`-able.

Nothing is dropped silently: every unmappable capability becomes a
`VecorelGap` on the render result, and `strict=True` turns the first one into
a raise.
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
from .exceptions import Kind, VecorelGap, VecorelUnrepresentable

__all__ = ["VecorelDocument", "SDL_SCHEMA_URI", "render_vecorel"]

SDL_SCHEMA_URI = "https://vecorel.org/sdl/v0.2.0/schema.json"

# The codegen's portable base-type names map almost one-to-one onto Vecorel's
# physical type vocabulary -- which is the finding, not a convenience. The two
# renames are float32/float64 -> float/double.
_PRIMITIVE_VECOREL_TYPES: dict[str, str] = {
    "int8": "int8",
    "int16": "int16",
    "int32": "int32",
    "int64": "int64",
    "uint8": "uint8",
    "uint16": "uint16",
    "uint32": "uint32",
    "uint64": "uint64",
    "float32": "float",
    "float64": "double",
    "str": "string",
    "bool": "boolean",
    "bytes": "binary",
    "Geometry": "geometry",
    "BBox": "bounding-box",
    "datetime": "date-time",
    "date": "date",
}

# Fallback keyed on the underlying Python type, for the constrained-string
# NewTypes the registry has no name entry for. `bool` precedes `int` because it
# is a subclass. `int` and `float` are deliberately ABSENT: Vecorel demands a
# width and a bare Python number does not carry one, so those raise a gap in
# `_primitive_type` rather than being silently widened to int64/double the way
# the codegen registry would.
_BUILTIN_VECOREL_TYPES: tuple[tuple[type, str], ...] = (
    (bool, "boolean"),
    (_dt.datetime, "date-time"),
    (_dt.date, "date"),
    (str, "string"),
    (bytes, "binary"),
)

# Vecorel's closed `format` vocabulary, keyed by the IR's Pydantic type name.
# Keyed by NAME rather than by `issubclass`: in Pydantic v2 neither `HttpUrl`
# nor `EmailStr` is a `str` subclass, so the builtin fallback below never
# reaches them and they would emit as an untyped `{}` -- which the metaschema
# rejects. Found by validating, not by reading.
_PYDANTIC_FORMATS: dict[str, str] = {
    "EmailStr": "email",
    "HttpUrl": "uri",
    "AnyUrl": "uri",
    "AnyHttpUrl": "uri",
    "UUID": "uuid",
}

# Vecorel's `geometryTypes` vocabulary is the GeoJSON spelling; Overture's
# GeometryType enum is snake_case. The rename is mechanical, but the set is not
# the same set: SDL has no `GeometryCollection`, so that member has no target.
_GEOMETRY_TYPE_NAMES: dict[str, str] = {
    "point": "Point",
    "line_string": "LineString",
    "polygon": "Polygon",
    "multi_point": "MultiPoint",
    "multi_line_string": "MultiLineString",
    "multi_polygon": "MultiPolygon",
}

_INTEGER_TYPES = frozenset(
    {"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"}
)
_NUMERIC_TYPES = _INTEGER_TYPES | {"float", "double"}


@dataclass
class VecorelDocument:
    """An emitted SDL document plus everything that did not survive the emit."""

    model: str
    content: dict[str, Any] | None
    gaps: tuple[VecorelGap, ...]

    @property
    def emitted(self) -> bool:
        return self.content is not None


@dataclass
class _Ctx:
    """Render state: the model name, the gap log, and the inline-recursion guard."""

    model: str
    gaps: list[VecorelGap] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)

    def gap(self, path: str, kind: Kind, capability: str, detail: str) -> None:
        self.gaps.append(VecorelGap(self.model, path or "/", kind, capability, detail))


def render_vecorel(spec: ModelSpec, *, strict: bool = False) -> VecorelDocument:
    """Render *spec* to a Vecorel SDL document using only the codegen IR.

    Returns the document and the gap log. A `UnionSpec` root returns
    `content=None`: Vecorel SDL has no union vocabulary, so the document does
    not exist rather than existing lossily. `strict=True` raises instead of
    returning a non-empty gap log.
    """
    ctx = _Ctx(model=spec.name)
    content: dict[str, Any] | None
    match spec:
        case RecordSpec():
            content = _render_root(spec, ctx)
        case UnionSpec():
            ctx.gap(
                "",
                "target-gap",
                "union",
                f"root is a discriminated union of {len(spec.members)} members; "
                "Vecorel SDL has no union, oneOf, anyOf or discriminator vocabulary, "
                "so no document is emitted at all",
            )
            content = None
        case _:
            assert_never(spec)
    gaps = tuple(ctx.gaps)
    if strict and gaps:
        raise VecorelUnrepresentable(gaps)
    return VecorelDocument(model=spec.name, content=content, gaps=gaps)


def _render_root(record: RecordSpec, ctx: _Ctx) -> dict[str, Any]:
    """Render the document root.

    The root's key set is closed, so two things that a nested object could
    carry have nowhere to go here: the model's own description, and `type`.
    """
    if record.description is not None:
        ctx.gap(
            "",
            "target-gap",
            "description (root)",
            "the SDL root permits only $schema/required/collection/properties "
            "under additionalProperties:false, so a model-level description "
            "cannot be expressed",
        )
    ctx.gap(
        "",
        "ir-gap",
        "default",
        "`default` is part of SDL's universal vocabulary and `FieldSpec` has no "
        "slot for it, so no field can emit one. Stated once per document rather "
        "than per field: a renderer cannot count what its input never carries, "
        "and an unreportable absence is the silent omission this arm exists to "
        "avoid",
    )
    ctx.gap(
        "",
        "ir-gap",
        "collection",
        "every property is emitted as feature-level; the IR has no "
        "collection-vs-feature-level concept, so the `collection` block is "
        "omitted rather than computed -- an assumption, stated",
    )

    document: dict[str, Any] = {"$schema": SDL_SCHEMA_URI}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for f in record.fields:
        properties[f.name] = _render_field(f, ctx, f"/properties/{f.name}")
        if f.is_required:
            required.append(f.name)
        else:
            _log_optionality(f, ctx, f"/properties/{f.name}")
    if required:
        document["required"] = required
    document["properties"] = properties
    return document


def _log_optionality(f: FieldSpec, ctx: _Ctx, path: str) -> None:
    """Record what a non-required field loses (or gains) under SDL semantics.

    Vecorel defines nullable as exactly `not required`, so the two cases
    diverge in opposite directions: a `X | None` field loses the distinction,
    while a field that merely has a default is *widened* to admit null.
    """
    if f.is_optional:
        ctx.gap(
            path,
            "target-gap",
            "nullable",
            "no null type and no nullable keyword; Vecorel defines nullable as "
            "exactly `not required`, so the distinction is not expressible",
        )
    else:
        ctx.gap(
            path,
            "target-gap",
            "optional-but-not-nullable",
            "field has a default but is not None-able; Vecorel equates "
            "not-required with nullable, so the emit ADMITS null where the "
            "Pydantic model does not -- a widening, not a loss",
        )


def _render_field(f: FieldSpec, ctx: _Ctx, path: str) -> dict[str, Any]:
    """Render one field: its shape, plus the universal description keyword."""
    schema = _shape_to_schema(f.shape, ctx, path)
    if f.description is not None:
        schema["description"] = f.description
    return schema


def _render_object(record: RecordSpec, ctx: _Ctx, path: str) -> dict[str, Any]:
    """Render a nested `RecordSpec` as an inline Vecorel object.

    Inline is the only option: SDL has no `$defs`, so the record's name is
    lost at every use site. Recorded once per site, because the count of
    sites is the measure of what the target cannot hold.
    """
    if record.name in ctx.stack:
        ctx.gap(
            path,
            "target-gap",
            "recursion",
            f"`{record.name}` is reachable from itself and SDL has no $ref, "
            "so the type cannot be expressed at any depth",
        )
        raise VecorelUnrepresentable(tuple(ctx.gaps))
    ctx.gap(
        path,
        "target-gap",
        "named-type",
        f"record `{record.name}` inlines; SDL has no $defs/$ref, so the name "
        "does not survive",
    )
    ctx.stack.append(record.name)
    try:
        schema: dict[str, Any] = {"type": "object"}
        properties: dict[str, Any] = {}
        required: list[str] = []
        for f in record.fields:
            properties[f.name] = _render_field(f, ctx, f"{path}/properties/{f.name}")
            if f.is_required:
                required.append(f.name)
            else:
                _log_optionality(f, ctx, f"{path}/properties/{f.name}")
        schema["properties"] = properties
        if required:
            schema["required"] = required
        if record.description is not None:
            schema["description"] = record.description
        if any(isinstance(c, NoExtraFieldsConstraint) for c in record.constraints):
            # Vecorel's own default, so this is a no-op -- stated rather than
            # emitted, since emitting it would imply the default is otherwise.
            schema["additionalProperties"] = False
        return schema
    finally:
        ctx.stack.pop()


def _primitive_type(
    base_type: str, source_type: type | None, ctx: _Ctx, path: str
) -> tuple[str | None, dict[str, Any]]:
    """Resolve a `Primitive` to a Vecorel type name plus any extra keywords."""
    mapped = _PRIMITIVE_VECOREL_TYPES.get(base_type)
    if mapped is not None:
        return mapped, {}

    if base_type in ("int", "float"):
        ctx.gap(
            path,
            "ir-gap",
            "numeric width",
            f"`{base_type}` carries no storage width; Vecorel requires one "
            "and the codegen registry would silently alias it to "
            f"{'int64' if base_type == 'int' else 'double'}",
        )
        return None, {}

    if isinstance(source_type, type):
        if issubclass(source_type, Enum):
            return _enum_type(source_type, ctx, path)
        if issubclass(source_type, BaseModel):
            return None, _render_object(extract_model(source_type), ctx, path)
        fmt = _PYDANTIC_FORMATS.get(source_type.__name__)
        if fmt is not None:
            return "string", {"format": fmt}
        for py_type, name in _BUILTIN_VECOREL_TYPES:
            if issubclass(source_type, py_type):
                return name, {}
        if issubclass(source_type, int) or issubclass(source_type, float):
            ctx.gap(
                path,
                "ir-gap",
                "numeric width",
                f"`{base_type}` resolves to Python "
                f"{source_type.__name__}, which carries no storage width",
            )
            return None, {}

    ctx.gap(path, "renderer-gap", "unmapped type", f"no Vecorel type for `{base_type}`")
    return None, {}


def _enum_type(
    enum_cls: type[Enum], ctx: _Ctx, path: str
) -> tuple[str | None, dict[str, Any]]:
    """Render an enum inline as a string with an `enum` value list."""
    enum_spec = extract_enum(enum_cls)
    described = [m for m in enum_spec.members if m.description is not None]
    if described:
        ctx.gap(
            path,
            "target-gap",
            "enum member descriptions",
            f"`{enum_spec.name}`: {len(described)} of {len(enum_spec.members)} "
            "members carry a description; SDL's `enum` is a bare value list "
            "with nowhere to put one",
        )
    ctx.gap(
        path,
        "target-gap",
        "named-type",
        f"enum `{enum_spec.name}` inlines; SDL has no $defs/$ref",
    )
    values = [m.value for m in enum_spec.members]
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return "int64", {"enum": values}
    return "string", {"enum": values}


def _merge_constraints(
    schema: dict[str, Any],
    constraints: tuple[ConstraintSource, ...],
    ctx: _Ctx,
    path: str,
) -> None:
    """Merge each constraint into *schema*, logging what Vecorel cannot hold."""
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
            ctx.gap(
                path,
                "target-gap",
                "multipleOf",
                f"multipleOf={c.multiple_of}; SDL's numeric vocabulary is "
                "minimum/maximum/exclusiveMinimum/exclusiveMaximum only",
            )
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
        elif type(c).__name__ == "LinearReferenceRangeConstraint":
            # Fixed arity that DOES reach the IR as an explicit constraint --
            # the contrast with BBox, whose arity hides behind an opaque type.
            schema["minItems"] = 2
            schema["maxItems"] = 2
        elif type(c).__name__ == "JsonPointerConstraint":
            ctx.gap(
                path,
                "target-gap",
                "semantic format",
                "RFC 6901 JSON Pointer; SDL's `format` vocabulary is closed to "
                "email/idn-email/iri/uri/uuid, and the constraint is imperative "
                "rather than a regex the IR carries, so inventing a `pattern` "
                "here would be the renderer fabricating what it was given",
            )
        elif type(c).__name__ == "Strict":
            ctx.gap(
                path,
                "target-gap",
                "strict parsing",
                "Pydantic strictness governs input coercion, not the value set; "
                "SDL describes data at rest in already-typed encodings and has "
                "no parsing directive. Unexpressible, and immaterial",
            )
        elif type(c).__name__ == "Reference":
            ctx.gap(
                path,
                "target-gap",
                "typed reference",
                "the IR carries a typed relationship (this id refers to that "
                "model); neither SDL nor JSON Schema has a foreign-key concept, "
                "so this is the IR carrying MORE than the target can hold",
            )
        elif isinstance(c, GeometryTypeConstraint):
            # The JSON Schema arm had to drop this to a `$comment`; SDL has a
            # first-class slot for it -- but only after a value-vocabulary
            # translation, and only for the six members SDL names.
            names: list[str] = []
            for gt in c.allowed_types:
                mapped = _GEOMETRY_TYPE_NAMES.get(gt.value)
                if mapped is None:
                    ctx.gap(
                        path,
                        "target-gap",
                        "geometry type",
                        f"`{gt.value}` has no member in SDL's geometryTypes "
                        "vocabulary (Point/LineString/Polygon and their Multi "
                        "forms only)",
                    )
                    continue
                names.append(mapped)
            if names:
                schema["geometryTypes"] = names
        elif isinstance(compiled := getattr(c, "pattern", None), re.Pattern):
            schema["pattern"] = compiled.pattern
            ctx.gap(
                path,
                "target-dialect",
                "pattern dialect",
                "emitted verbatim; the pattern is a Python `re` source and SDL "
                "inherits JSON Schema's ECMA-262 dialect",
            )
            min_len = getattr(c, "min_length", None)
            if isinstance(min_len, int):
                schema["minLength"] = min_len
            max_len = getattr(c, "max_length", None)
            if isinstance(max_len, int):
                schema["maxLength"] = max_len
        else:
            ctx.gap(
                path,
                "renderer-gap",
                "unmapped constraint",
                f"{type(c).__name__} has no Vecorel mapping in this renderer",
            )


def _prune_for_type(schema: dict[str, Any], ctx: _Ctx, path: str) -> None:
    """Drop keywords SDL does not allow for the schema's own type.

    SDL's vocabulary is type-conditional, so a keyword valid on one type is a
    validation error on another -- `enum` on a float, for instance. Dropping is
    only honest if it is recorded, so each drop is a gap.
    """
    t = schema.get("type")
    if t == "float" or t == "double":
        if "enum" in schema:
            del schema["enum"]
            ctx.gap(
                path,
                "target-gap",
                "enum (floating point)",
                "SDL permits `enum` for strings and integers only",
            )
    if t not in _NUMERIC_TYPES:
        for kw in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
            if kw in schema:
                del schema[kw]
                ctx.gap(
                    path,
                    "target-gap",
                    f"{kw} (non-numeric)",
                    f"SDL scopes {kw} to numeric types; type is {t!r}",
                )
    if t != "string":
        for kw in ("minLength", "maxLength", "pattern", "format"):
            if kw in schema:
                del schema[kw]
                ctx.gap(
                    path,
                    "target-gap",
                    f"{kw} (non-string)",
                    f"SDL scopes {kw} to strings; type is {t!r}",
                )


def _shape_to_schema(shape: FieldShape, ctx: _Ctx, path: str) -> dict[str, Any]:
    """Render one `FieldShape` layer (and its descendants) to an SDL schema."""
    match shape:
        case Primitive(base_type=base_type, source_type=source_type, constraints=cs):
            name, extra = _primitive_type(base_type, source_type, ctx, path)
            schema: dict[str, Any] = dict(extra)
            if name is not None:
                schema = {"type": name, **schema}
            _merge_constraints(schema, cs, ctx, path)
            _prune_for_type(schema, ctx, path)
            return schema

        case LiteralScalar(values=values, constraints=cs):
            literal: dict[str, Any] = {}
            plain = [v.value if isinstance(v, Enum) else v for v in values]
            if all(isinstance(v, str) for v in plain):
                literal = {"type": "string", "enum": list(plain)}
            elif all(isinstance(v, int) and not isinstance(v, bool) for v in plain):
                literal = {"type": "int64", "enum": list(plain)}
            else:
                ctx.gap(
                    path,
                    "target-gap",
                    "literal",
                    f"Literal{list(plain)!r} is neither all-string nor "
                    "all-integer; SDL has no `const` and scopes `enum` to "
                    "strings and integers",
                )
            if len(plain) == 1:
                ctx.gap(
                    path,
                    "target-gap",
                    "const",
                    "a single-valued Literal emits as a one-element `enum`; "
                    "SDL has no `const` keyword",
                )
            _merge_constraints(literal, cs, ctx, path)
            return literal

        case AnyScalar(constraints=cs):
            ctx.gap(
                path,
                "target-gap",
                "Any",
                "`type` is required and its enum is closed, so an untyped "
                "value cannot be expressed",
            )
            any_schema: dict[str, Any] = {}
            _merge_constraints(any_schema, cs, ctx, path)
            return any_schema

        case ModelRef(model=model, starts_cycle=starts_cycle):
            if starts_cycle:
                ctx.gap(
                    path,
                    "target-gap",
                    "recursion",
                    f"`{model.name}` is a cycle back-edge; SDL has no $ref so "
                    "the type cannot be expressed at any depth",
                )
                return {}
            return _render_object(model, ctx, path)

        case UnionRef(union=union):
            ctx.gap(
                path,
                "target-gap",
                "union",
                f"`{union.name}` is a discriminated union of "
                f"{len(union.members)} members; SDL has no union vocabulary "
                "and no discriminator",
            )
            return {}

        case ArrayOf(element=element, constraints=cs):
            array_schema: dict[str, Any] = {
                "type": "array",
                "items": _shape_to_schema(element, ctx, f"{path}/items"),
            }
            _merge_constraints(array_schema, cs, ctx, path)
            return array_schema

        case MapOf(key=key, value=value, constraints=cs):
            map_schema: dict[str, Any] = {"type": "object"}
            key_pattern = _key_pattern(key)
            rendered_value = _shape_to_schema(
                value, ctx, f"{path}/additionalProperties"
            )
            if key_pattern is not None:
                # SDL has patternProperties but no propertyNames, so a
                # constrained key is expressed by pattern-keying the value.
                map_schema["patternProperties"] = {key_pattern: rendered_value}
            else:
                map_schema["additionalProperties"] = rendered_value
            _merge_constraints(map_schema, cs, ctx, path)
            return map_schema

        case NewTypeShape(name=name, inner=inner):
            ctx.gap(
                path,
                "target-gap",
                "named-type",
                f"NewType `{name}` inlines; SDL has no $defs/$ref, so the "
                "semantic name does not survive",
            )
            return _shape_to_schema(inner, ctx, path)

        case _:
            assert_never(shape)


def _key_pattern(key: FieldShape) -> str | None:
    """Return the first regex pattern reachable on a map's key shape."""
    for cs in all_constraints(key):
        compiled = getattr(cs.constraint, "pattern", None)
        if isinstance(compiled, re.Pattern):
            source = compiled.pattern
            assert isinstance(source, str)
            return source
    return None
