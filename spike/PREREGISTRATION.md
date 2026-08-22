# Pre-registered predictions

Written **before** the renderer emitted anything, from reading the IR
(`extraction/specs.py`, `extraction/field.py`) and the 15 baselines. Recorded so
the census is scored against a prediction rather than rationalised after the
fact. Each line names the classification the bead asks for — *codegen bug*, *IR
gap*, *deliberate improvement* — plus a fourth the bead does not have and the
census needs: **renderer scope**, where the IR carries it and this throwaway
renderer was simply never specced to emit it. Collapsing that into "IR gap"
would be the single easiest way to manufacture a finding.

| # | prediction | count in baselines | classification | basis |
|---|---|---|---|---|
| 1 | `default` missing from every emit | 14 (9 distinct sites: `connectors=[]` ×3, `is_max_speed_variable=false`, `class`/`subtype` land+water, `level=0`) | **IR gap** | `FieldSpec` is `name, shape, description, is_required, is_optional`. There is no default anywhere in the IR. Structurally certain, not a guess. |
| 2 | `uniqueItems` missing | 68 | **renderer scope**, NOT an IR gap | The source is an explicit `UniqueItemsConstraint()` in the `Annotated[...]` (e.g. `places/place.py:71`, `common/perspectives.py:34`), so it reaches the IR as a `ConstraintSource`. My spec's constraint table omits it, so it will surface as `$comment: unmapped constraint`. My first guess — that set-ness was lost because `ArrayOf` has no set variant — was wrong; reading the declaration corrected it. |
| 3 | `format` missing | 4 sites (`date-time`, `email`, `uri` ×2) | **renderer scope**, recoverable | The IR has `PydanticTypeSpec` for `HttpUrl`/`EmailStr` and friends, carrying `source_type`. The format string is derivable from it; `PRIMITIVE_TYPES` just has no entry. |
| 4 | `if` / `then` (22 each) and most of `not` (65) missing | 109 | **renderer scope** | `RecordSpec.constraints` / `UnionSpec.constraints` carry `ModelConstraint`s (RequireIf, ForbidIf, RadioGroup, MinFieldsSet, RequireAnyOf…). The spec mapped only `NoExtraFieldsConstraint`. The IR has the rest. |
| 5 | `required` arrays diverge | 203 sites | **IR gap** (already filed as `bd-8dqw`) | codegen conflates nullable with not-required; JSON Schema's `required` is where that becomes visible output. Pre-registered by the bead; expect it to fire. |
| 6 | emitted-only `$defs` for NewTypes | — | **deliberate improvement** | `NewTypeShape` keeps the NewType's name; Pydantic dissolves it into anonymous keywords. Measured by the `--defs` arm, which the lockstep walk erases by design. |
| 7 | emitted `discriminator` where segment's ROOT has bare `oneOf` | 1 | **deliberate improvement** | Callable-discriminator unions only — see the correction in checkpoint 2. The three *nested* `vehicle` unions already carry `discriminator` on the Pydantic side, so a divergence THERE is a codegen bug, not a win. |
| 8 | `title` matches on properties | 699 | — | Specced to Pydantic's `record_id -> "Record Id"` convention. A large `title` column means the convention is wrong, which is cosmetic. |
| 9 | `examples` appears on neither side | 0 in baselines | note | `extraction/examples.py` is 367 lines, so the IR carries examples the Pydantic schema does not emit. Not a divergence here because neither side emits it — but it is a *second* deliberate improvement available for free, and worth saying so rather than leaving it invisible. |

Scoring rule fixed in advance: a keyword that appears in the census but not in
this table is an unanticipated finding and gets its own line in the report. A
prediction that does not fire gets said so explicitly.

## A fourth classification the bead does not have: *schema-only, not in the model*

Found while ground-truthing row 5. `Place`'s extracted `RecordSpec.constraints`
is **empty** — yet the place baseline carries `additionalProperties: false` and
`patternProperties: {"^ext_.*$": …}`. Neither is derived from the model. They are
written by hand in a second JSON-Schema hook,
`OvertureFeature.__get_pydantic_json_schema__`
(`packages/overture-schema-common/src/overture/schema/common/feature.py:78`),
which injects both onto the properties sub-object after the `Feature` hook has
built the envelope.

The Python model says the *opposite*: `model_config = ConfigDict(extra="allow")`
(feature.py:44), with the real restriction enforced at runtime by a separate
`model_validator` that rejects extras not prefixed `ext_`. So the JSON Schema is
deliberately stricter than the Pydantic model, and the strictness exists only in
the hook.

Consequence for the census: `additionalProperties` (130 occurrences) and
`patternProperties` (28) are **not IR gaps**. Nothing in the IR could carry them,
because nothing in the *model* states them — an extractor cannot extract what was
never declared. Counting them as IR gaps would inflate the headline finding with
content that a perfect extractor would also miss.

Three hand-written JSON-Schema sources are now identified, all outside the model:
the `Feature` GeoJSON envelope (feature.py:471, ~145 lines), the `OvertureFeature`
`ext_` allowlist (feature.py:78), and `GenerateOmitNullableOptionalJsonSchema`'s
null-stripping (`system/json_schema.py:15`). Together they are what "Pydantic's
own JSON Schema" actually means in this repo, and none of the three is IR-shaped.
