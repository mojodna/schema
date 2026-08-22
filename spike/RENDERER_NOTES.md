# Renderer notes

Dated findings from building `json_schema/renderer.py` and `json_schema/pipeline.py`.
Written the moment each is hit, per the task's PERSIST-AS-YOU-GO instruction. Read
alongside `spike/PREREGISTRATION.md`, which predicts several of these from reading
the IR before any code ran.

- 2026-08-22: Confirmed via `union_extraction.py:258-270` that `UnionSpec` is
  constructed without a `constraints=` kwarg, so `UnionSpec.constraints` is always
  the dataclass default `()`. The field exists (shared base shape with `RecordSpec`)
  but is dead for unions specifically -- no union ever carries a `NoExtraFieldsConstraint`
  or anything else through this path. Not a renderer decision, a fact about the IR.

- 2026-08-22: Decision point on "never silently drop" vs "follow the spec exactly".
  `RecordSpec.constraints` / `UnionSpec.constraints` can carry `ModelConstraint`s other
  than `NoExtraFieldsConstraint` (RequireIf, ForbidIf, RadioGroup, MinFieldsSet,
  RequireAnyOf...) per `extraction/model_constraints.py`. The spec's mapping table only
  says what to do with `NoExtraFieldsConstraint` (-> `additionalProperties: false`); it
  gives no instruction for the rest. I considered adding a generic
  `$comment: "unmapped model constraint: <ClassName>"` for the others, matching the
  spirit of "never silently drop" and the pattern already used for field-shape
  constraints -- but `PREREGISTRATION.md` item 4 explicitly predicts these show up
  missing entirely (not commented) as a "renderer scope" finding, i.e. the spike wants
  to measure them as absent, the same way `if`/`then`/`not` are absent from Pydantic's
  emit path here. Went with the literal spec: only `NoExtraFieldsConstraint` is handled
  at the model level; other `ModelConstraint`s are not mapped and produce no output at
  all (not even a comment). Flagging this explicitly rather than let the choice look
  like an oversight.

- 2026-08-22: The spec's NewTypeShape row says the `$defs` entry holds "the inner
  shape's schema" with no mention of `title`/`description`, unlike the enum row (which
  explicitly lists `title`/`description`). Rendered NewType `$defs` entries carry no
  title or description, even though `NewTypeSpec` (via `newtype_extraction.py`) has
  both available. This is a second source of `title`/`description` divergence beyond
  the deliberate "NewType stays a named $ref" one -- worth separating in the census:
  "IR had a name for this $defs entry, renderer didn't render its metadata."

- 2026-08-22: Self-referential cycles. When a `RecordSpec`'s own field graph contains
  a `ModelRef` cycle back to itself (`starts_cycle=True` on the back-edge), the root
  document ends up with a `$defs` entry for its own name in addition to being the root
  document -- the root's own schema is duplicated into `$defs/<RootName>` too. The spec
  doesn't call this out explicitly ("$defs holding every referenced record" — a
  self-reference is technically "referenced"). Implemented it that way since it's the
  only way the `$ref` back-edge resolves within the document, but noting it as a spec
  gap rather than an obviously-intended behavior.

- 2026-08-22: The unresolved-`BaseModel`-`Primitive` case (`Primitive.source_type` is a
  `BaseModel` subclass, meaning extraction had no `model_resolver` and left it
  unresolved rather than producing a `ModelRef`) has no `RecordSpec` sitting in the IR
  to render as its `$defs` entry -- only the bare class. Handled by calling
  `extraction.model_extraction.extract_model(cls)` directly (a public extraction
  entrypoint, not a modification to extraction) to materialize one on demand. Whether
  this path is ever actually exercised by the 15 baseline feature types is unconfirmed;
  logging it here in case the acceptance run never hits it and this code path goes
  untested.

- 2026-08-22: Full 15-file generate against the real registry (not a synthetic
  fixture) succeeded on the first run with no exceptions and no dangling `$ref`s
  (checked by hand with a small script before writing the formal test). Confirms the
  IR is complete enough for a from-scratch renderer with no special-casing per
  feature type -- no feature needed a workaround. `segment.json` is the largest
  document (81 `$defs`, 156 `$ref`s, root is a discriminated `UnionSpec` over
  `RoadSegment`/`RailSegment`/`WaterSegment`), and it round-tripped cleanly too.

- 2026-08-22: `NestedClass.When`-style dotted names (e.g. `AccessRule.When`,
  `DestinationRule.When`, `SpeedLimitRule.When`, `ProhibitedTransitionRule.When`,
  `SpeedLimitRule.When`) show up as `RecordSpec.name` / `$defs` keys in `segment.json`.
  This comes straight from the IR (I key `$defs` by `RecordSpec.name` unless a union
  member overrides it with `member_cls.__name__`), not something this renderer
  invented. A literal `.` in a `$defs` key is a valid JSON object key and a valid JSON
  Pointer reference-token (only `/` and `~` are special in JSON Pointer), so
  `#/$defs/AccessRule.When` resolves correctly -- verified by the ref-resolution test.
  Flagging only because it looks unusual next to the golden baselines, which likely
  use Pydantic's flattened/anonymous naming for the same nested classes.

- 2026-08-22: `MapOf` and its `propertyNames` pattern path both got real exercise:
  `CommonNames` (a map keyed by BCP-47-ish language tag, value `StrippedString`)
  renders with `additionalProperties: {"$ref": "#/$defs/StrippedString"}` and a
  `propertyNames.pattern` picked up from the key shape's constraint; `SourceTags`
  (map to `Any`) renders `additionalProperties: {}` with no `propertyNames`, correctly
  reflecting that its key shape carries no pattern constraint.

- 2026-08-22: `uv run mypy` (no args, whole workspace) fails before it reaches any of
  my files: `packages/overture-schema-pyspark/tests/conftest.py` collides with
  `packages/overture-schema-codegen/tests/conftest.py` as "Duplicate module named
  conftest". This is pre-existing (present before this spike touched anything, and
  unrelated to `json_schema/` or `cli.py`) -- confirmed by running mypy scoped to just
  the new files and `cli.py`, which passes cleanly. Not fixing it: out of scope for a
  throwaway renderer spike, and touching shared test infra risks exactly the kind of
  side effect the spike is supposed to avoid.
