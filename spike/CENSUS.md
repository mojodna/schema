# JSON Schema codegen parity: divergence census

Spike for `bd-jsonschema-codegen-parity-spike-k9co`. Throwaway renderer, real
measurements. Everything below is measured on this worktree at
`spike/jsonschema-codegen-parity`; commands are in `spike/`.

## The question changed once, before any output existed

The bead asks whether the codegen extraction IR carries everything Pydantic's
`model_json_schema()` carries, with the 15 golden baselines as the fixed target.

The baselines are not Pydantic core output. Three hand-written layers sit between
the models and the files:

| layer | where | what it does |
|---|---|---|
| GeoJSON envelope | `system/feature.py:471` (~145 lines) | moves every field except `id`/`bbox`/`geometry` into a `properties` sub-object, inserts `type: {const: Feature}`, migrates `additionalProperties`/`patternProperties`/`allOf`/`if`… down with them, adds `not: {required: [id, bbox, geometry]}`, makes the sub-object nullable when nothing in it is required |
| `ext_` allowlist | `common/feature.py:78` | injects `patternProperties: {"^ext_.*$": …}` and `additionalProperties: false` onto the sub-object |
| null stripping | `system/json_schema.py:15` | removes `null` from nullable-optional fields and drops `default: null` |

The IR models the flat record — the columnar view. Diffing a flat emit against an
enveloped baseline measures the envelope, not the IR: **294 divergences across the
15 documents come from the envelope alone** (`census.py --no-unwrap`). So the
census canonicalises first, inverting the envelope on the baseline side
(`unwrap_geojson`), and what survives is the parity question.

Consequence that outlives the spike: `additionalProperties` (130 occurrences) and
`patternProperties` (28) **cannot be IR gaps**. Nothing in the model declares
them — `OvertureFeature` sets `model_config = ConfigDict(extra="allow")`, the
*opposite*, with the real restriction enforced by a runtime `model_validator`.
The JSON Schema is deliberately stricter than the Pydantic model and the
strictness lives only in a hook. An extractor cannot extract what was never
declared.

## The classification needs four buckets, not three

The bead's three are *codegen bug* / *IR gap* / *deliberate improvement*. Two more
were forced by the material:

- **renderer scope** — the IR carries it; this throwaway renderer was never
  specced to emit it. Collapsing this into "IR gap" is the easiest way to
  manufacture a finding.
- **schema-only** — not in the model either, so no extractor could carry it (the
  three hook layers above).

## Instrument controls

An empty column is worth nothing until the instrument is shown to fire, so every
zero below is paired with a control run on the population the fault would live in.

| control | result |
|---|---|
| identity: each un-enveloped baseline against itself, all 15 | 0 divergences — no false-positive floor |
| injected `drop-pattern` | +207 reported |
| injected `drop-description` | +916 reported |
| injected `perturb-type` (string→integer) | +538 reported |
| `required` comparison, one field's requiredness flipped per model, nested population | 36/36 reported |
| enum comparison, one member dropped per enum | 41/41 reported |
| `unwrap_geojson` content loss | 153 leaf values lost, all 17×{`false`, `"string"`, `"object"`, `"type"`, `"id"`, `"bbox"`, `"geometry"`, `"Feature"`, `"properties"`} — exactly the envelope machinery, 17 envelopes (14 roots + 3 inside segment's `$defs`). 0 gained. |

## Results not requiring the renderer

### `required` — the bead's headline prediction does not fire, and the zero is a base-rate artefact

`bd-8dqw` predicts codegen's nullable/not-required conflation surfaces here.
Measured: 14 top-level features, 0 divergences; 35 valid nested comparisons, 0
divergences. Control passes 36/36.

The zero is not evidence. **394 fields across 53 reachable records contain 209
nullable fields and 0 that are nullable *and* required** — the only configuration
in which the conflation is observable. Overture declares every nullable field as
`X | None = None`, so nullable implies has-a-default implies not-required, by
authoring convention. The census cannot test `bd-8dqw` on these models; it needs a
synthetic model with a required nullable field.

(One apparent nested mismatch was an artefact of joining `$defs` by bare type
name: `$defs["Address"]` in the place baseline is Place's nested address record,
not the Address feature. Name-keyed joins across documents are unsound; the
`--defs` arm carries the same hazard.)

### enums — a parity result that does survive its controls

41 enums compared by name, **0 value-set mismatches**, over 759 members, control
41/41. The IR's enum vocabulary reproduces Pydantic's exactly.

### deliberate improvements, measured rather than asserted

1. **Discriminator structure on callable-discriminator unions.** The bead states
   the loss as "a discriminated union collapses into a bare `anyOf`". That is
   wrong in general: the three nested `vehicle` unions in segment carry a full
   `discriminator: {propertyName, mapping}` on the Pydantic side, because
   `VehicleSelector` uses `Field(discriminator="dimension")` — a string. The
   Segment *root* is bare `oneOf` because `Feature.field_discriminator` returns a
   **callable** `Discriminator`, from which Pydantic cannot derive a
   `propertyName`. Since every Overture feature union goes through that helper,
   the loss lands exactly on the top-level feature unions and nowhere else — and
   `feature.py:239` documents that the callable carries `_field_name` precisely so
   introspection can recover it, which is why the IR can. Restated: a divergence
   on a *string*-discriminator union is a codegen bug, not a win.
2. **Readable `$defs` naming under collision.** Four classes named `When` force
   Pydantic to disambiguate by module path
   (`overture__schema__transportation__segment___common__AccessRule__When`); the
   IR disambiguates by owner (`AccessRule.When`). 4 sites, all in segment.
3. **Per-member enum descriptions.** 74 of 759 members (19 of 43 enums) carry a
   description in the IR. JSON Schema's `enum` is a bare value list with nowhere
   to put them; expressing them needs `oneOf` of `{const, description}`. This one
   differs in kind from the first two: it is a limit of the *target language*, not
   of Pydantic's emitter, and only the latter is a candidate for "fix the emitter".

All three are invisible to the lockstep walk by construction — it resolves `$ref`
on each side within its own document so that naming differences do not register —
which is why the `--defs` arm exists.

## The census

Emit with `uv run overture-codegen generate --format json-schema --output-dir <dir>`,
then `python3 spike/census.py --emitted <dir> --repo .` and
`python3 spike/classify.py <dir> .`.

**760 divergences across the 15 documents.** The first run produced 1520; two
systematic renderer misses accounted for half of it, and fixing them is what makes
the residual worth reading.

| bucket | n | % |
|---|---:|---:|
| renderer scope | 439 | 57.8% |
| cosmetic (`title` convention) | 151 | 19.9% |
| schema-only (not in the model) | 66 | 8.7% |
| target dialect (regex) | 55 | 7.2% |
| **IR gap** | **48** | **6.3%** |
| deliberate improvement | 1 | 0.1% |

### The IR gap column, in full — two causes, 48 sites

- **Field defaults, 14.** `FieldSpec` is `(name, shape, description, is_required,
  is_optional)`. There is no default anywhere in the IR, so `connectors=[]`,
  `is_max_speed_variable=false`, `level=0` and the `class`/`subtype` literals are
  unreachable. Structural, not an oversight to patch in a renderer.
- **`BBox` arity, 34** (`minItems`/`maxItems` = 4, at each of 17 roots). `bbox`
  reaches the IR as `Primitive(base_type="BBox")` — a terminal with an entry in
  `PRIMITIVE_TYPES` and no internal structure. The four-element arity lives behind
  the opaque type. Note the contrast one line over: `SourceItem.between` is also a
  fixed-arity pair, and its 44 `min/maxItems` are *not* an IR gap, because the
  arity rides on an explicit `LinearReferenceRangeConstraint` that does reach the
  IR. Same symptom, different cause — which is the whole reason the census
  classifies by mechanism rather than by keyword.

Everything else that looks like a gap is not one.

### What the other buckets are

**renderer scope (439)** — the IR carries it; this throwaway renderer was specced
without it. The largest are `$comment` markers for constraint classes the spec's
table never listed (`LinearReferenceRangeConstraint` 44, `JsonPointerConstraint`
17, `Strict` 11, `GeometryTypeConstraint` 16), `type` alongside `const` on literal
fields (62), and NewType `$defs` entries carrying no description (53). Each is a
line of renderer, not a fact about the IR.

**schema-only (66)** — `additionalProperties` and `patternProperties`, written by
`OvertureFeature.__get_pydantic_json_schema__`, contradicted by the model's own
`extra="allow"`. No extractor can reach them.

**target dialect (55)** — every one is a Python `\Z` where JSON Schema has `$`.
The IR carries the compiled pattern's source verbatim; JSON Schema requires
ECMA-262. That is a translation step every JSON Schema target owes, and it is
neither an IR gap nor an emitter bug. The two sibling census beads (Vecorel SDL,
STAC `table:columns`) will each have their own version of this, and it is worth
naming as its own bucket there too.

**cosmetic (151)** — the `record_id -> "Record Id"` title convention, applied
where Pydantic differs.

### Two renderer defects worth reporting, because of what they cost

1. **Registry-keyed primitives lose the type.** `_primitive_schema` looked up
   `PRIMITIVE_TYPES` by the codegen base-type NAME, which has no entry for the
   repo's constrained-string NewTypes (`StrippedString`, `LanguageTag`,
   `CountryCodeAlpha2`, …), so 297 fields emitted `$comment: unmapped` instead of
   `{"type": "string"}`. The IR had it the whole time: `Primitive.source_type` is
   literally `<class 'str'>`. Falling back to the Python type fixed all of them.
   *This is the failure mode the census is most at risk of: a renderer's lookup
   miss reads exactly like an IR gap.*
2. **A shared `$def` leaks use-site constraints.** Constraints attach at the use
   site, not to the NewType, so registering one `$defs/<NewType>` from the first
   use and `$ref`-ing it everywhere put `VehicleAxleCountSelector`'s `le=100` and
   `multipleOf=1` onto height, length, weight and width. Now a use whose rendered
   schema differs from the cached one is inlined instead. The consequence
   generalises: **the NewType-identity win is only available where the NewType's
   own constraints are the whole story** — elsewhere it costs either the shared
   name or `$ref`-with-siblings.

### The vocabulary arm — the deliberate improvements, measured

The lockstep walk resolves `$ref` on each side within its own document, so naming
differences never register. Measured separately (`census.py --defs`):

- **48 distinct domain type names** the IR names as `$defs` and Pydantic dissolves
  into anonymous inline keywords: `Id`, `StrippedString`, `LanguageTag`,
  `ConfidenceScore`, `FeatureVersion`, `WikidataId`, `Sources`, `CommonNames`,
  `AdminLevel`, `HexColor`, `Hierarchy`, `OpeningHours`, `SpeedValue`, … Per
  document, 9 (connector) to 34 (segment) emit-only names.
- **0 base-only `$defs` in 14 of 15 documents.** Segment's 4 are the module-path
  mangled `overture__schema__transportation__segment___common__AccessRule__When`
  keys, whose IR counterparts appear on the emitted side as `AccessRule.When`.
- **`discriminator`: 3 on the baseline side, 4 on the emitted side.** The extra one
  is the Segment root — the callable-discriminator case Pydantic cannot express.

### Controls, run on the emitted population

The bead requires that an empty column be scrutinised as hard as a large one, so
the walk was re-controlled against the real emit (not just baseline-vs-baseline):
`drop-pattern` +124, `drop-description` +822, `perturb-type` +424 — all REPORTS,
verdict PASS.

### Scoring the pre-registration

| # | prediction | outcome |
|---|---|---|
| 1 | `default` missing, 14 | **fired exactly**, IR gap |
| 2 | `uniqueItems` renderer scope, not IR gap | **fired**, and the correction held — it was an `Annotated` constraint all along |
| 3 | `format` renderer scope | fired (3 residual after the datetime fallback) |
| 4 | `if`/`then`/`not` renderer scope | fired |
| 5 | `required` diverges (`bd-8dqw`) | **did not fire — and cannot.** 0 of 394 fields are nullable *and* required |
| 6 | emitted-only NewType `$defs` | fired, 48 names |
| 7 | `discriminator` on segment's root | fired, 1 site |
| 8 | `title` matches | **did not fire** — 151 cosmetic divergences; the convention guess was wrong |
| 9 | `examples` on neither side | held |

Unanticipated, and the report's own additions: the GeoJSON envelope, the
`ext_` hook, the target-dialect bucket, and the two renderer defects above.

## Answering the bead

*Does the IR carry everything `model_json_schema()` carries?* On these 15 models:
**yes, except field defaults and `BBox` arity.** 48 of 760 divergences, two causes,
both nameable in a sentence. The claim the bead set out to test — that the IR is a
faithful model of the schema rather than a docs-shaped projection of it — survives.

*Where does it carry more?* 48 named domain types, one discriminator, and 74
enum-member descriptions the target language cannot hold at all.

**One caveat that limits the whole result:** the ground truth is not Pydantic's
core emitter but three hand-written layers on top of it, and the largest of them —
the GeoJSON envelope — is not IR-expressible. If codegen ever became the JSON
Schema generator, that ~145 lines moves with it as a separate projection step.
