# Vecorel SDL codegen target: the census

Emit Vecorel SDL from the `overture-schema-codegen` extraction IR alone, and count what
does not survive — in both directions. Predictions were fixed in
`spike/VECOREL_PREREGISTRATION.md` before any document was emitted; every one is scored
below, including the two that did not fire and the one that fired only after a defect
was found.

Reproduce:

    uv run overture-codegen generate --format vecorel --output-dir spike/vecorel-out
    uv run --with jsonschema python spike/validate_vecorel.py spike/vecorel-out
    uv run --with jsonschema python spike/validate_vecorel.py spike/vecorel-out --control
    uv run python spike/vecorel_census.py
    uv run python spike/vecorel_census.py --control
    uv run python spike/keyword_census.py spike/vecorel-out

## The headline

**The IR is not the constraint here. The target is.**

    kind             n      %     what it is a claim about
    target-gap     873   82.0%    Vecorel SDL cannot hold it
    target-dialect 163   15.3%    both can hold it, differently
    ir-gap          28    2.6%    the codegen IR does not carry it
    renderer-gap     0    0.0%    this renderer did not try

The JSON Schema arm asked whether the IR was a faithful model of the schema or a
docs-shaped projection, and answered *faithful, 6.3% gap*. This arm asks the same
question against a smaller target and gets **2.6%** — and both of that column's two
causes are the *same* cause, `default`, which the IR has no slot for. The other,
`collection`, is a Vecorel concept with no Pydantic counterpart at all.

So the two arms agree on the finding that matters: **`default` is the codegen IR's one
real gap**, and it reproduces identically against two unrelated targets. A gap that
appears against one target is a target artefact. A gap that appears against both is a
property of the IR.

## What did not survive, by mechanism

    target-gap      named-type                    421
    target-gap      nullable                      325
    target-dialect  pattern dialect               163
    target-gap      enum member descriptions       31 sites
    target-gap      const                          28
    target-gap      optional-but-not-nullable      18
    target-gap      description (root)             14
    ir-gap          default                        14  (once per document)
    ir-gap          collection                     14  (once per document)
    target-gap      semantic format                14
    target-gap      strict parsing                 10
    target-gap      typed reference                 7
    target-gap      Any                             4
    target-gap      union                           1

### `named-type` (421) is the tax on having no `$defs`, and it compounds

SDL's root permits exactly `$schema`, `required`, `collection`, `properties`, under
`additionalProperties: false`. There is no `$defs`, no `$ref`, and no other reuse
mechanism — confirmed against the metaschema, the SDL README's closed vocabulary list,
and two real published SDL documents.

Every record, NewType and enum therefore inlines at every use site, and its name is
gone. The JSON Schema arm's headline *win* — 48 named domain types (`Id`,
`ConfidenceScore`, `LanguageTag`, `OpeningHours`…) that Pydantic dissolves into
anonymous keywords but the IR keeps — is a *loss* here. Same IR, opposite verdict,
because the constraint moved from the emitter to the language.

The compounding is the second-order finding and it explains the shape of the whole
table. Because every use inlines a fresh copy, **every other loss is multiplied by the
number of use sites**. Nullability is the clean demonstration: 209 distinct nullable
fields in the IR, **325** nullable sites in the emitted documents. The two numbers
measure different things and both are correct; reporting either alone would mislead.

### `nullable` (325 sites / 209 distinct fields) — Vecorel mandates the conflation

Vecorel has no `null` type and no `nullable` keyword. Nullability is *defined* as the
complement of `required`, and the reference implementation enforces the equivalence:
`vecorel_cli/parquet/types.py` sets `nullable=not required`, the GeoParquet validator
errors when actual column nullability disagrees, and the GeoJSON writer actively drops
null-valued properties rather than emitting them.

This is worth stating precisely, because it inverts the sibling arm's result on the
same question. The JSON Schema arm predicted the nullable-vs-required conflation
(`bd-8dqw`) would show up and found it **untestable**: not one of 394 fields is both
nullable and required, so nothing discriminates. Here the target *mandates* the
conflation — there is no way to express the distinction, so the question is not "does
the emitter conflate them" but "the language does."

And it bites in the direction nobody predicts. 18 fields are optional-but-not-`None`-able
— they have a Pydantic default but the model does not admit `null`. Emitted as
not-`required`, Vecorel semantics say they *are* nullable. **That is a widening, not a
loss**: the emitted schema accepts data the Pydantic model rejects. A census that only
counted what got dropped would score these 18 as clean.

### `pattern dialect` (163) — the bucket that must not be charged to the IR

Every emitted `pattern` is a Python `re` source; SDL inherits JSON Schema's ECMA-262
dialect. 163 sites, 15.3% of the total. The JSON Schema arm hit the same wall at 55
sites and warned the sibling arms to keep this bucket separate. Folding it into "IR gap"
would have turned a 2.6% gap into an 18% one and produced exactly the wrong conclusion.

### The IR carries more than either target can hold

Three kinds, and they are not the same kind:

- **`typed reference` (7).** `Reference` annotates a typed relationship — this id refers
  to that model, with a named role. Neither SDL nor JSON Schema has a foreign-key
  concept. This is the strongest IR-carries-more finding in either arm, because it is
  not a formatting difference: it is information no schema language in this family
  represents.
- **`enum member descriptions` (31 sites).** SDL's `enum` is a bare value list, exactly
  like JSON Schema's. Same loss, same reason, in both arms.
- **`named-type` (421)**, above — a win against Pydantic's emitter, a loss against SDL.

### Where Vecorel is *more* expressive than JSON Schema

Two of the JSON Schema arm's problems simply do not exist here, and both were predicted:

- **`bounding-box`.** BBox was that arm's second-largest IR gap: 34 divergences, because
  `minItems`/`maxItems` = 4 sits behind an opaque `Primitive(base_type="BBox")`. SDL has
  a first-class `bounding-box` type, so the arity never needs expressing. **14 sites
  emit natively, 0 exceptions.**
- **`geometryTypes`.** `GeometryTypeConstraint` has no JSON Schema keyword and became a
  `$comment` there. SDL has a first-class slot. **14 sites, 32 member values.**

Both required a value-vocabulary translation the design did not anticipate: SDL's
`geometryTypes` uses the GeoJSON spelling (`MultiPolygon`), Overture's enum is
snake_case (`multi_polygon`), and SDL's list has no `GeometryCollection` member. The
capability transfers; the vocabulary does not.

## Validity, and the control that makes it readable

**10 of 14 emitted documents validate** against the SDL metaschema. Two independent
instruments agree — `jsonschema` Draft 2020-12 against the fetched metaschema, and the
real `vecorel-cli 0.2.15` `vec validate-schema` — case for case on the documents spot-
checked against both.

All four failures reduce to **one** cause: `SourceTags = dict[str, Any]`. SDL requires
`type` on every subschema and its enum is closed, so an untyped value cannot be
expressed, and the four documents carrying `source_tags` cannot be made valid without
inventing a type the IR does not carry. The PySpark renderer faces the same input and
silently assumes `MapType(StringType(), StringType())`; this arm declines to make the
same guess quietly.

The control ran first, on the emitted population rather than a healthy one: four
injected defects (drop `type`, out-of-vocabulary type name, top-level `$id`, unknown
root key) × 14 documents = **56/56 reported**. The 10/14 is a measurement only because
of that.

### An upstream defect, confirmed on the real tool

The metaschema's root carries
`"patternProperties": {"^$": {"description": "Allow $id, $comments and similar meta
properties."}}`. The regex `^$` matches only the empty-string key, so with root
`additionalProperties: false` a top-level `$id` is **rejected** — the stated intent is
not implemented. Presumably `^\$` was meant.

Confirmed twice: as 14/14 in the control above, and by running a synthetic document with
a top-level `$id` through the real `vec validate-schema`, which fails with `'$id' does
not match any of the regexes: '^$'`. Notably the CLI's own `VecorelSchema` class assigns
`$id` to loaded schemas in memory — the codebase treats `$id` as legitimate while its
own validator rejects it on disk.

## The pre-registered predictions, scored

| # | prediction | result |
|---|---|---|
| P1 | `default` is an IR gap, cross-target: 0 emitted | **FIRED** — 0 emitted, 14 stated. See the note below on *how* it fired. |
| P2 | 209 nullable fields lose the distinction | **FIRED, and larger** — 325 sites / 209 distinct, plus 18 widened. |
| P3 | unions unrepresentable; the union root emits no document | **FIRED exactly** — Segment emits nothing; 0 nested union sites, because all union use is inside Segment. |
| P4 | 4 `Any` sites raise | **FIRED exactly** — 4, and they are what blocks 4 documents from validating. |
| P5 | no named type survives | **FIRED** — 421 sites; 0 of 53 records, 44 NewTypes, 41 enums keep a name. |
| P6 | the BBox gap inverts: 0 exceptions | **FIRED** — 14 `bounding-box` sites, 0 exceptions, against 34 divergences in the sibling arm. |
| P7 | ≥10 of 17 geometry sites emit `geometryTypes` | **FIRED** — 14 of 14 documents, 32 member values. |
| P8 | `multipleOf` raises, `VehicleAxleCountSelector` among them | **DID NOT FIRE — 0, and the reason is the finding.** |
| P9 | 74 enum member descriptions dropped | **FIRED, count disputed** — 71 by an independent walk, not 74. See below. |
| P10 | `collection` emits 0, stated not implied | **FIRED** — 0 emitted, 14 stated. |
| P11 | 14 of 15 validate; top-level `$id` fails | **PARTLY** — 14 emitted but **10** valid; the `$id` half confirmed on two instruments. |
| P12 | exactly 3 `format` sites | **FIRED exactly — 3** (1 email, 2 uri), but only after a defect was fixed. |

### P8 did not fire, and that is the most instructive line in the table

`multipleOf` is genuinely outside SDL's numeric vocabulary, and the corpus genuinely
contains `VehicleAxleCountSelector`'s `multiple_of=1`. It scores zero because that
constraint lives in **Segment** — the one model that emits no document at all. The
union gap swallowed the `multipleOf` gap.

This is the same failure shape the sibling arm caught with `required`, one level up: a
zero that reads as "the target handles it" when the truth is "the population never
reached the instrument." Control C4 feeds a synthetic `multiple_of=2` through the same
renderer and it REPORTS, which is the only reason the zero is readable at all.

Generalising: **when one gap removes a whole model from the population, every other gap
in that model silently scores zero.** Nothing in the census output says so.

### P12 fired, and would have read as a clean zero

Predicted exactly 3 `format` sites; measured exactly 3. But the first implementation
resolved Pydantic types with `issubclass(source_type, str)`, and in Pydantic v2 neither
`HttpUrl` nor `EmailStr` is a `str` subclass. They fell through to an untyped `{}`,
which would have scored as **0 format sites and 3 renderer gaps** — a plausible-looking
result. Metaschema validation caught it; reading the code did not. The same class of
error as the sibling arm's registry-lookup-by-name defect, in a different disguise.

### P9's count is disputed, and the discrepancy is not resolved

The sibling arm reports 74 described enum members across 19 of 43 reachable enums. An
independently written walk here finds **71 across 18 of 41**. The likely cause is that
this walk excludes the RootModel alias specs (`extract_alias_spec`) that the markdown
path adds, so it reaches two fewer enums — but that is **UNVERIFIED**, and a 4%
disagreement between two counts of the same quantity is worth naming rather than
smoothing. Only **29** of them are reachable in the 14 emitted documents; the rest live
in Segment.

### How P1 fired matters more than that it fired

`FieldSpec` is `(name, shape, description, is_required, is_optional)`. There is no
default slot, so **the renderer cannot emit a per-field gap for `default` — it never
sees one to miss.** An absence that cannot be reported is exactly the silent omission
this arm was built to avoid, and the first version of the renderer had it: the `default`
column was simply empty, and looked like every other clean column.

It is now stated once per document, as an assumption rather than a count. Same for
`collection`, which has no IR counterpart at all. The rule generalises past this spike:
**a renderer can only count what its input carries, so a gap in the input is invisible
to the very instrument built to measure gaps** — it has to be asserted from outside.

## Two defects in this renderer, found by scoring rather than by reading

Recorded because both produced numbers that looked fine.

1. **Nullability was logged at the root but not inside nested objects.** The column
   measured the renderer's own structure rather than the corpus, and read *low* — the
   flattering direction. Caught by comparing 116 against the pre-registered 209.
2. **`default` was unreportable**, above.

Neither was caught by the test suite, by lint, or by inspection. Both were caught by
having written the expected numbers down first.

## What this says for the third arm (STAC `table:columns` + Ossie)

- Keep `target-dialect` a separate bucket from `ir-gap`. It was 7.2% of the JSON Schema
  arm and 15.3% here; folding it in would have inverted this arm's headline.
- Expect the flattening target to make `named-type` worse, not better —
  `table:columns` is flatter than SDL, which is already flat.
- **Check whether a gap has removed a model from the population before reading any zero
  in that model's other columns.** P8 is the case; it will recur wherever a target
  cannot express Overture's one union.
- `default` should reproduce a third time. If it does not, this arm's conclusion is
  wrong.

## Register

Spike. Throwaway quality by design. Promotion of the renderer is out of scope; the
deliverable is this census and the exception list.

Verification: `make check` — 6200 passed, ruff and mypy clean. Metaschema validation and
all controls as reported above.
