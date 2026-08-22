# Vecorel SDL arm: pre-registration

Written **before** any Vecorel emit, so the census cannot be read backwards off its own
output. Same discipline as `spike/PREREGISTRATION.md` (the JSON Schema arm), and the same
scoring rule: each prediction gets FIRED / DID-NOT-FIRE / UNTESTABLE, and an
"untestable" is reported as loudly as a hit.

## What is different about this arm

The JSON Schema arm had a ground-truth emitter in the repo, so its census was a
**divergence diff** against 15 baselines. Nothing emits Vecorel SDL from these models, so
there is no baseline to diff. This arm's census is therefore a **coverage-and-exception
census**: walk the corpus, classify every site, and count. Its ground truth is the SDL
metaschema (`https://vecorel.org/sdl/v0.2.0/schema.json`, fetched and read), which
validates the *emitted* documents.

That makes an empty exception column even more dangerous here than there: with no
baseline, nothing contradicts a renderer that quietly emits something plausible. Hence
the controls in the last section, which are pre-committed rather than added afterwards.

## Corpus, measured before emitting (`spike/probe_corpus.py`)

    entry points          15   (1 of them a UnionSpec)
    reachable records     53
    fields               394     nullable 209 · required 164 · nullable AND required 0
    named NewTypes        44
    enums                 41
    UnionRef sites         3
    cycle back-edges       0
    MapOf sites            6
    AnyScalar sites        4
    LiteralScalar sites   42

These reproduce the JSON Schema arm's independently-derived counts (53 / 394 / 209 / 0)
from a separately written walk, which is the reason to trust the walk at all.

## Corrections to the bead, from reading the metaschema and the IR first

Three of the bead's stated premises are wrong, and one is half-wrong. Recorded here
because a premise corrected after the numbers arrive is indistinguishable from a
rationalisation.

1. **"Integer width. Vecorel demands `int8`..`uint64`; Python `int` carries no width."**
   The *IR* carries width. `Primitive.base_type` is already `int32` / `float64` /
   `int64` — the codegen registry's portable names — and **not one field in the corpus
   reaches the renderer as a bare `int` or `float`** (0 of 394). The predicted headline
   IR gap cannot fire here. What survives of the concern is narrower and still real: the
   registry *aliases* bare `int` to int64 and `float` to float64, so a model authored
   without a width would be silently widened rather than raised on. That is a latent
   defect the corpus does not exercise, and control **C1** exists to prove the renderer
   would catch it.

2. **"`bounding-box` … confirm each is genuinely unreachable from the IR."**
   The opposite. `BBox` reaches the IR as an opaque `Primitive(base_type="BBox")` — which
   was the JSON Schema arm's *second-largest IR gap* (34 divergences: `minItems`/`maxItems`
   = 4 sitting behind the opaque type). Vecorel has a first-class `bounding-box` type, so
   the arity never needs expressing. 17 sites. See P6: this arm predicts the gap inverts.

3. **"Vecorel's own metaschema permits any JSON Schema 2020-12 keyword."**
   Half true, and the half that is false matters. A *property* subschema permits extra
   keywords (`$defs/schema` sets no `additionalProperties: false`). The *document root*
   forbids them: root `additionalProperties: false`, with only `$schema`, `required`,
   `collection`, `properties` allowed.

4. **A probable upstream defect, found while reading the root.** The metaschema carries
   `"patternProperties": {"^$": {"description": "Allow $id, $comments and similar meta
   properties."}}`. The regex `^$` matches only the empty-string key — `$id` does not
   match it — so with root `additionalProperties: false` the stated intent is not
   implemented and a top-level `$id` is *rejected*. Presumably `^\$` was meant. P11
   tests this against the emitted documents rather than asserting it.

## Predictions

Numbered, each with the count it would take to falsify it.

- **P1 — `default` is an IR gap, cross-target.** `FieldSpec` is
  `(name, shape, description, is_required, is_optional)`; there is no default slot
  anywhere in the IR. Vecorel *has* `default`. Predict: **0 `default` keywords emitted**,
  against ~14 fields that carry a Pydantic default (the JSON Schema arm's count). This is
  the one gap expected to reproduce identically across both targets, which is what makes
  it an IR property rather than a target artefact.

- **P2 — nullability is a target gap, and Vecorel forces the very conflation
  `bd-8dqw` is about.** The SDL type enum has no `null` and there is no `nullable`
  keyword. Predict: **all 209 nullable fields lose the distinction**, expressible only as
  absence from `required`. Vecorel *cannot* distinguish "may be null" from "may be
  absent". Note the shape of this: the JSON Schema arm found the conflation untestable
  because no field is both nullable and required; here the target itself mandates it.

- **P3 — unions are unrepresentable.** Vecorel SDL has no union, `oneOf`, `anyOf`, or
  discriminator vocabulary at all. Predict: **3 raised exceptions at `UnionRef` sites**,
  and **1 of the 15 entry points (the `UnionSpec`) cannot be emitted as a Vecorel
  document at all** — not a lossy emit, an absent one.

- **P4 — `Any` is unrepresentable.** `type` is required and the enum is closed. Predict
  **4 raised exceptions**, one per `AnyScalar` site.

- **P5 — named types have nowhere to go.** No `$defs`, no `$ref`: the root permits only
  `$schema`/`required`/`collection`/`properties`. Predict **0 of the 53 records, 44
  NewTypes and 41 enums survive as names**; every nesting inlines. The JSON Schema arm's
  headline *win* — 48 named domain types Pydantic dissolves into anonymous keywords —
  is a *loss* here, against the target rather than against the emitter. Corollary:
  recursion is inexpressible. The corpus has 0 cycles, so this does not fire on these
  models; control **C3** proves the renderer would raise rather than recurse forever.

- **P6 — the BBox gap inverts.** Predict **17 `bounding-box` sites emit natively, 0
  exceptions**, against 34 divergences charged to this same type in the JSON Schema arm.

- **P7 — geometry types stop being a comment.** `GeometryTypeConstraint` had no JSON
  Schema keyword and became a `$comment` in that renderer. Vecorel has `geometryTypes`.
  Predict **at least 10 of the 17 `Geometry` sites emit a populated `geometryTypes`**.

- **P8 — `multipleOf` is a target gap.** Vecorel's numeric vocabulary is
  minimum/maximum/exclusiveMinimum/exclusiveMaximum only. Predict **>0 raised**, and
  specifically that `VehicleAxleCountSelector`'s `multipleOf=1` is among them.

- **P9 — enum member descriptions are lost again, for the same reason.** Vecorel `enum`
  is a bare value list, exactly like JSON Schema's. Predict **74 member descriptions
  dropped** — the JSON Schema arm's number, reproduced. If it differs, one of the two
  counts is wrong.

- **P10 — `collection` has no IR concept.** Predict **0 emitted**, and that the renderer
  must *state* the every-property-is-feature-level assumption rather than leave it
  implicit. An unstated assumption here is indistinguishable from a considered one.

- **P11 — metaschema validity.** Predict **14 of 15 emitted documents validate** against
  the SDL metaschema (the 15th being the union entry point of P3, which is not emitted).
  Separately predict that adding a top-level `$id` **fails** validation, confirming the
  `^$` reading in correction 4.

- **P12 — `format` is nearly unused.** Vecorel allows only email/idn-email/iri/uri/uuid.
  The corpus has `EmailStr` (1) and `HttpUrl` (2). Predict **3 `format` sites**;
  `JsonPointer` (1), `PhoneNumber` (1) and `WikidataId` (7) have no Vecorel format and
  must fall back to `pattern`.

## Controls, pre-committed

An exception column of zero is a claim about the world only if the renderer would have
reported. Each control is a synthetic model fed through the same renderer, with a
non-empty expected result.

- **C1 — bare `int`.** A model with `x: int`. The renderer must **raise or flag
  width-unknown**, not silently emit `int64`. Proves the P1-adjacent latent defect is
  detectable even though the corpus has 0 occurrences.
- **C2 — required-and-nullable.** A model with a field that is both. Must be flagged.
  The corpus cannot produce one (0 of 394), so this is the only way the P2 machinery is
  exercised in the direction that discriminates.
- **C3 — recursion.** A self-referential model. Must raise, not recurse.
- **C4 — the validator is not blind.** Mutate an emitted document (drop a `type`, inject
  an out-of-vocabulary type name) and assert metaschema validation **fails**. A passing
  P11 means nothing until this passes.

C1–C3 assert a *did-happen* on the same instrument as the did-not-happens they license,
and C4 controls the apparatus rather than the subject.
