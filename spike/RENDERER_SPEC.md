# Spike: JSON Schema renderer from the codegen IR

Bead: `bd-jsonschema-codegen-parity-spike-k9co` (schema-workspace queue).
Register: **spike, throwaway quality**. The deliverable is a divergence census,
not a shippable renderer. Do not refactor extraction. Do not touch
`overture-schema-system`'s `json_schema.py` — that is the ground-truth side.

## Goal

Emit a JSON Schema document for a `ModelSpec` (`RecordSpec | UnionSpec`) using
ONLY the codegen extraction IR, so its output can be diffed against the 15
golden baselines at `packages/*/tests/*_baseline_schema.json` (produced by
Pydantic's `model_json_schema()` via `GenerateOmitNullableOptionalJsonSchema`).

Divergence is the *result*, not a failure. Do not consult the baselines while
writing the renderer and do not special-case toward them: the census is
worthless if the renderer was fitted to the answer. Emit what the IR says.

## Where

`packages/overture-schema-codegen/src/overture/schema/codegen/json_schema/`
(sibling of `markdown/` and `pyspark/`), with:

- `renderer.py` — `render_json_schema(spec: ModelSpec) -> dict[str, Any]`
- `pipeline.py` — `generate_json_schema_documents(specs) -> list[JsonSchemaDocument]`
  where `JsonSchemaDocument` has `.path: PurePosixPath` (`<snake_case_name>.json`)
  and `.content: str` (JSON, `indent=2`, `sort_keys=True`, trailing newline).

Wire into `codegen/cli.py`: add `"json-schema"` to `_OUTPUT_FORMATS` and a
branch in `generate()` that writes the documents via `_write_output`. Keep the
existing `--tag/--filter/--exclude/--output-dir` behaviour.

Respect the package's strict downward-import rule: `json_schema/` may import
from `extraction/` and `layout/`, never from `markdown/` or `pyspark/`.

## Mapping rules (IR -> JSON Schema)

Root document: the model's own schema, plus a `$defs` object holding every
referenced record, enum and NewType, keyed by its IR name. Use
`{"$ref": "#/$defs/<Name>"}` for references. Emit `$defs` only when non-empty.

`RecordSpec` ->
```
{"type": "object", "title": <name>, "description": <description if not None>,
 "properties": {<field name>: <field schema>},
 "required": [<names of fields with is_required True>]  # omit when empty
 "additionalProperties": false                          # iff the spec carries
                                                        # NoExtraFieldsConstraint
}
```
Per field, wrap the shape schema with `"description"` from `FieldSpec.description`
(when not None) and `"title"` = the field name title-cased with `_` -> space
(`record_id` -> `"Record Id"`), matching Pydantic's convention. Emit `title` on
properties only, not on `$defs` members other than their own model title.

`UnionSpec` -> `{"oneOf": [<$ref per member>], "title": <name>,
"description": <description>}` plus, when `discriminator_field` is set,
`"discriminator": {"propertyName": <field>, "mapping": {<tag>: <$ref>}}`.
Members go in `$defs` by class `__name__`; use `member_specs[].spec` for their
`RecordSpec`. Also emit the union's merged `annotated_fields`? **No** — the
union document is the oneOf; do not flatten.

`FieldShape` variants:

| variant | emit |
|---|---|
| `Primitive` | primitive base-type mapping (below), or `$ref` to `$defs` for an enum / BaseModel `source_type` |
| `LiteralScalar` | one value -> `{"const": v}`; several -> `{"enum": [...]}` |
| `AnyScalar` | `{}` |
| `ModelRef` | `{"$ref": "#/$defs/<model.name>"}`; recurse into `model` unless `starts_cycle` |
| `UnionRef` | inline the union schema shape above (its members still go to `$defs`) |
| `ArrayOf` | `{"type": "array", "items": <element>}` |
| `MapOf` | `{"type": "object", "additionalProperties": <value>}`; if the key shape carries a pattern constraint, also emit `propertyNames` |
| `NewTypeShape` | `{"$ref": "#/$defs/<name>"}` with the `$defs` entry holding the inner shape's schema — this is the deliberate divergence the spike is looking for; do NOT inline it |

Primitive base types (`extraction/type_registry.PRIMITIVE_TYPES` names):
`int8/int16/int32/int64/uint8/uint16/uint32/int` -> `{"type": "integer"}`;
`float32/float64/float` -> `{"type": "number"}`; `str` -> `{"type": "string"}`;
`bool` -> `{"type": "boolean"}`; `Geometry` -> `{"type": "object"}`;
`BBox` -> `{"type": "array", "items": {"type": "number"}}`.
An unrecognised base type whose `source_type` is an `Enum` subclass -> `$ref` to
a `$defs` entry `{"type": "string", "enum": [<member values>], "title": <name>,
"description": <description>}` (use `extraction.enum_extraction` if it helps).
An unrecognised base type whose `source_type` is a `BaseModel` subclass -> `$ref`.
Anything else unrecognised: emit `{"$comment": "unmapped: <base_type>"}` — an
explicit marker, never a silent omission, so the census can count it.

Constraints (`ConstraintSource.constraint`, from `annotated_types` and the
codegen length classes) merge into the schema object of the layer they attach to:

| constraint | keyword |
|---|---|
| `Ge` | `minimum` |
| `Gt` | `exclusiveMinimum` |
| `Le` | `maximum` |
| `Lt` | `exclusiveMaximum` |
| `Interval` | whichever of the four are set |
| `MultipleOf` | `multipleOf` |
| `ScalarMinLen` / `ScalarMaxLen` | `minLength` / `maxLength` |
| `ArrayMinLen` / `ArrayMaxLen` | `minItems` / `maxItems` |
| anything exposing a compiled `.pattern` | `pattern` (the `re.Pattern.pattern` source) |
| `GeometryTypeConstraint` | `{"$comment": "geometry types: <values>"}` |
| any other | `{"$comment": "unmapped constraint: <ClassName>"}` |

Again: an unmapped constraint is a `$comment`, never a drop. The census counts
`$comment` markers as "renderer did not carry it", which is a different finding
from "the IR did not have it".

## Acceptance

1. `uv run overture-codegen generate --format json-schema --output-dir <dir>`
   writes 15 files without raising, for the 15 baseline feature types
   (address, bathymetry, infrastructure, land, land_cover, land_use, water,
   building, building_part, division, division_area, division_boundary, place,
   connector, segment).
2. Every emitted document parses as JSON and every `$ref` resolves within its
   own document (no dangling `#/$defs/X`). Write that as a test under
   `packages/overture-schema-codegen/tests/` — it is the only test the spike
   needs.
3. `uv run ruff check` and `uv run mypy` (as the repo configures them) pass on
   the new files.

Leave all edits in the working tree. Do NOT commit, do NOT push.
