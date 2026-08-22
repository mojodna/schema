# Vecorel SDL codegen spike — findings

Investigation started 2026-08-22.
Already established: SDL metaschema at https://vecorel.org/sdl/v0.2.0/schema.json fetched and read (see task prompt for its content summary). Not re-deriving.

## Q1. NULLABILITY — RESOLVED

Vecorel SDL has no `null`/`nullable` type or keyword anywhere in its vocabulary (confirmed: the `type` enum in the metaschema `$defs.schema.properties.type.enum` is exactly the 18 types listed in the task prompt, no `null`). There is **no distinct concept of "null" vs "absent"** in the SDL itself. Nullability is entirely a *derived* property from `required`:

- **Core spec** (`core/README.md`, https://github.com/vecorel/specification/blob/main/core/README.md): properties not listed in `required` are simply undecorated (no "optional"/"nullable" keyword used at all — e.g. `bbox` has no REQUIRED marker and is documented only as "The bounding box of the geometry.").

- **GeoParquet encoding spec** (https://github.com/vecorel/specification/blob/main/geoparquet/README.md, saved locally as `geoparquet-encoding-readme.md`), quoted verbatim:
  > "Properties that are optional can be omitted if all values are [null values](https://parquet.apache.org/docs/file-format/nulls/), i.e. the column can be missing from the GeoParquet file."
  This explicitly equates "optional" (not in `required`) with "nullable," and treats an all-null column and an absent column as interchangeable.

- **Reference implementation, `vecorel-cli` v0.2.15** (installed via `uvx --from vecorel-cli`, source inspected at `/Users/seth/.cache/uv/archive-v0/d3ak7qRKCYjU6Ojm/lib/python3.12/site-packages/vecorel_cli`):
  - `vecorel_cli/parquet/types.py:128`: `return pa.field(name, pa_type, nullable=not required)` — a PyArrow field is nullable **iff** the property is not in `required`. This is the literal mechanism.
  - `vecorel_cli/validation/geoparquet.py:75-79`:
    ```python
    # Does the field (dis)allow null?
    nullable = key not in schema.get("required", [])
    if not has_multiple_collections and nullable != pq_field.nullable:
        self.error(f"{key}: Nullability differs, is {pq_field.nullable} but must be {nullable}")
    ```
    The validator asserts this equivalence and errors if a GeoParquet file's actual column nullability disagrees with `required`.
  - `vecorel_cli/datasets/template.py:113`, the CLI's own scaffold-generator template, has the comment: `"required": ["my_id"],  # i.e. non-nullable properties` — the maintainers' own plain-language gloss on the semantics.
  - `vecorel_cli/encoding/geojson.py:314-330` (`GeoJSON.fix_geo_interface` / `_fix_omit_nulled_properties`): on GeoJSON write, any property whose value is `None` is recursively **popped from the properties object** rather than written as `"key": null`. So in the canonical GeoJSON encoding, null is normalized away to absence — the two are made equivalent by the writer, not just permitted to coexist.

**Answer:** A non-required property is implicitly nullable; Vecorel does not distinguish "absent" from "null" — required properties must always have a non-null value, non-required properties may be null or absent interchangeably (and the reference tooling actively collapses null → absent on GeoJSON write, and permits an all-null column to be physically dropped in GeoParquet). There is no way in SDL to express "required-but-nullable" or "optional-but-must-be-present-and-non-null" — required ⟺ non-nullable is a hard equivalence baked into the reference implementation, not just a convention.

Sources:
- https://github.com/vecorel/specification/blob/main/core/README.md
- https://github.com/vecorel/specification/blob/main/geoparquet/README.md
- https://github.com/vecorel/cli (PyPI package `vecorel-cli`, installed/inspected locally, v0.2.15)

---

## Q2. $defs / $ref / reuse — RESOLVED

**No mechanism exists for named reusable type definitions in an SDL document.** Confirmed three ways:

1. **Vocabulary list is exhaustive and closed.** `sdl/README.md` §Vocabulary lists exactly: top-level `$schema`, `required`, `properties`, `collection`; per-schema `type` (required), `deprecated`, `default`, `description`; then type-conditional keywords per data type. No `$ref`, `$defs`, `definitions`, or similar appears anywhere in this vocabulary.
2. **The metaschema's own top-level shape forbids it.** `additionalProperties: false` at the document root (https://vecorel.org/sdl/v0.2.0/schema.json), with only `$schema`, `required`, `properties`, `collection` in `properties` — a document-level `$defs` block would be rejected outright (confirmed live, see Q7 below — same `additionalProperties:false` mechanism that rejects `$id`).
3. **`$ref`/`$defs` DO appear inside the metaschema itself**, but only as JSON Schema 2020-12 machinery the metaschema author uses to define *its own* validation vocabulary recursively (e.g. `$defs.schema` refers to itself via `#/$defs/schema` to describe nested `items`/`properties`/`contains` sub-schemas). This is not exposed to SDL document authors — an SDL author cannot write `$ref: "#/$defs/something"` pointing at a named type they defined once; every nested `schema` object (property, array `items`, `contains`, `patternProperties` value, `additionalProperties` value) must be a fully inlined `{type: ..., ...}` object.

**Implication for recursive/self-referential types:** they cannot be expressed. There is no way to write a schema like `type: object; properties: {children: {type: array; items: <same type as this object>}}` — SDL has no self-reference or forward-reference syntax, no external `$ref` to another schema fragment, nothing. A tree-shaped or otherwise recursive property (e.g. nested sub-geometries, a linked-list-of-properties pattern) is inexpressible in SDL as written; the practical workaround visible in real documents is to keep `object`/`array` nesting shallow and duplicate any repeated substructure verbatim at each occurrence (verified — no real example schema found uses more than one level of `object`/`array` nesting; see Q6). Reuse *across* documents is achieved only at the whole-document level via the `schemas` composition/merge mechanism (see Q3), never at the sub-schema/type level.

Sources: https://github.com/vecorel/sdl/blob/main/README.md, https://vecorel.org/sdl/v0.2.0/schema.json (fetched, saved as `sdl-metaschema-v0.2.0.json`), `vecorel_cli` source (no `$ref`-resolution code found for user-authored SDL documents, only for the metaschema itself, jsonschema lib internals).

---

## Q3. EXTENSIONS — RESOLVED

Extensions are **separate SDL documents**, each with their own `$schema` (same SDL metaschema URI as core) and their own distinct identity URI, composed at the *Collection*'s `schemas` property (a list of schema URIs — see core README example in scratch file `core-readme.md` lines 40-54, collection `xyz` lists both the core schema URI and a crop-extension schema URI). Confirmed live with a real extension:

- **Administrative Division Extension** (https://github.com/vecorel/administrative-division-extension), README quoted:
  > "Identifier: https://vecorel.org/administrative-division-extension/v0.1.0/schema.yaml"
  > "Property Name Prefix: admin"
  Its schema file (fetched raw, saved as `vecorel-example-administrative-division-extension.yaml`):
  ```yaml
  $schema: https://vecorel.org/sdl/v0.2.0/schema.json
  required:
    - admin:country_code
  properties:
    admin:country_code:
      type: string
      minLength: 2
      maxLength: 2
      pattern: ^[A-Z]{2}$
    admin:subdivision_code:
      type: string
      minLength: 1
      maxLength: 3
      pattern: ^[A-Z0-9]{1,3}$
  ```
  This **does** use `$schema: https://vecorel.org/sdl/v0.2.0/schema.json` — the identical SDL metaschema as core — and it validates successfully: `uvx --from vecorel-cli vec validate-schema vecorel-example-administrative-division-extension.yaml` → `VALID`.

- **Namespacing is a flat colon-prefix convention baked into the property key string itself** (`admin:country_code`), not a structural/nested namespace. There is no SDL keyword for "namespace" — it's purely a naming convention documented per-extension ("Property Name Prefix: admin") and enforced by author discipline, not by the metaschema (nothing in the metaschema restricts property-name characters beyond being valid JSON Schema object keys).

- **Merge mechanism, from `vecorel_cli/vecorel/schemas.py`** (reference implementation):
  - `VecorelSchema.merge_all(*schemas)`: deep-copies the first schema, strips its `$id`, then folds in each subsequent schema via `.merge()`.
  - `VecorelSchema.merge(self, other)`:
    - `self["required"] = list(set(self["required"]) | set(other.get("required", [])))` — required lists are unioned.
    - `collection` dict entries are merged key-by-key, **raising `ValueError` on conflict** (`"Schema has conflicts in 'collection': Property '{key}' has values '{a}' and '{b}'."`) if two schemas disagree about collection-vs-feature-level for the same key.
    - `properties` are merged recursively via `_merge_properties`.
    - Guard: `if self.get_sdl_version() != other.get_sdl_version(): raise ValueError("Schemas have different SDL versions, can't merge.")` — all composed schemas must target the same SDL metaschema version.
  - `Collection.merge_schemas()` (`vecorel_cli/vecorel/collection.py`) resolves every URI in the Feature/Collection's `schemas` list (plus any `schemas:custom` inline override) and calls `merge_all` on the resolved set — this is literally what happens before validating a data file against "the" effective schema.

**Answer:** extensions are ordinary SDL documents under the same metaschema, composed by URI-list + deep-merge (union required/properties, conflict-check collection-level flags), with property-name collisions avoided purely by a documented (not enforced) colon-prefix naming convention, not a structural namespace mechanism.

Sources: https://github.com/vecorel/administrative-division-extension, `vecorel_cli/vecorel/schemas.py`, `vecorel_cli/vecorel/collection.py` (installed package, inspected locally).

---

## Q4. COLLECTION vs FEATURE level — RESOLVED

**SDL keyword**, `sdl/README.md` line 24, quoted verbatim:
> `collection`: Specifies whether a property (specified as keys) must be provided only at the collection-level (`true`) or only at the feature-level (`false`). Omit any properties that can be provided at both levels.

**Core spec**, `core/README.md`, quoted verbatim:
> "Encodings may support to store properties that consists of the same value across all features at the collection-level. This de-duplicates data for more efficient resource usage, but only applies if more than two features are available for the collection. The specific location and behaviour of collection-level data is specified in the encoding-specific specifications."

The real core schema (`core-schema-v0.1.0.yaml` / `vecorel-example-core-schema.yaml`) sets `collection: {schemas: true, id: false, geometry: false, bbox: false}` — i.e. `schemas` is collection-only, the rest are feature-only (none use `true`/`false` ambiguously — all four core properties are pinned one way, consistent with "omit if provided at both levels").

**Encoding-level consequences, confirmed in the reference CLI:**

- **GeoJSON** (`vecorel_cli/encoding/geojson.py`):
  - Line 113-115, writing features: `collection_only = collection.get_collection_only_properties(); ... if key not in collection_only: <write into Feature.properties>` — a `collection: true` property is **excluded from every Feature's `properties` object**.
  - Line 172 / 288: such properties are instead written directly onto the **FeatureCollection object itself** (`collection[key] = value`), i.e. a top-level member of the `FeatureCollection` JSON object, sibling to `type`/`features`.

- **GeoParquet** (`vecorel/specification` repo, `geoparquet/README.md`, quoted verbatim):
  > "Properties can also be stored at the collection-level if all values in a column have the same value. This de-duplicates data for more efficient resource usage and simplifies the structure of the Parquet file. The GeoParquet file must embed the properties in the Parquet metadata in a property named `collection`. The metadata must be JSON-encoded."
  I.e. a `collection: true` property is **not a Parquet column at all** — it's pulled out entirely and embedded as JSON inside the Parquet file-level key-value metadata under the key `collection`, rather than as a per-row column value.

**Answer:** `collection: true` = collection-level-only (GeoJSON: a member of the `FeatureCollection` object, not `Feature.properties`; GeoParquet: JSON-encoded in file-level Parquet metadata under key `collection`, not a column). `collection: false` = feature-level-only (GeoJSON: `Feature.properties` member; GeoParquet: an ordinary column). Omitting a property from the `collection` map means it may appear at either level depending on encoding/dataset needs.

Sources: https://github.com/vecorel/sdl/blob/main/README.md, https://github.com/vecorel/specification/blob/main/core/README.md, https://github.com/vecorel/specification/blob/main/geoparquet/README.md, `vecorel_cli/encoding/geojson.py` (installed package, inspected locally).

---

## Q5. VECOREL CLI — RESOLVED (positive: schema-validation path exists)

Installable and ground-truthed live (not just read from README):

```
uvx --from vecorel-cli vec --help
```
(PyPI package name is **`vecorel-cli`**, console entrypoint is **`vec`** — not `vecorel`.) `pip install vecorel-cli` also works per its README (pip/pipx not available in this sandbox to double-check, but `uvx` confirms the package resolves and installs cleanly from PyPI: "Installed 56 packages in 174ms").

Top-level commands (from `vec --help`, v0.2.15):
```
convert, converters, create-geojson, create-geoparquet, create-stac-collection,
describe, improve, jsonschema, merge, rename-extension, validate, validate-schema
```

**There IS a dedicated schema-validation path, distinct from data validation:**

```
vec validate-schema --help
Usage: vec validate-schema [OPTIONS] [FILES]...
  Validates a Vecorel schema file.
Options:
  -m, --metaschema PATH_OR_URL  Vecorel SDL metaschema to validate against.
                                 [default: https://vecorel.org/sdl/v0.2.0/schema.json]
  --help                        Show this message and exit.
```
vs. `vec validate` which validates a *data* file (GeoJSON/GeoParquet) against the resolved schema(s), not an SDL document against the metaschema.

Live-tested:
```
uvx --from vecorel-cli vec validate-schema vecorel-example-core-schema.yaml
=> VALID          # exit code 0
uvx --from vecorel-cli vec validate-schema test-toplevel-id.yaml   # our synthetic $id test
=> INVALID (see Q7)   # exit code STILL 0 (see caveat below)
```

**Caveat / minor bonus finding (not asked, flag anyway):** the process exit code was `0` in both the VALID and INVALID cases in this session's test — `vec validate-schema` appears not to signal failure via exit status, only via printed `-` (red) vs `=>` (green) output. Worth confirming before wiring this into a CI/codegen gate that checks `$?`.

**Answer to the load-bearing question:** a *schema* (SDL document) validation path exists and works, separate from data validation — `vec validate-schema <file>` against the default (or `-m`-overridden) metaschema. This is not a negative finding.

Sources: https://github.com/vecorel/cli, PyPI `vecorel-cli` (installed and run locally via `uvx --from vecorel-cli`).

---

## Q6. REAL SDL EXAMPLES — RESOLVED

Saved to scratchpad (all **YAML** in practice — every real example found, including the metaschema-conformant core spec and the one real extension checked, is `.yaml`, not `.json`; only the metaschema itself is `.json`):

1. `vecorel-example-core-schema.yaml` — the actual Vecorel core schema, fetched from https://vecorel.org/specification/v0.1.0/schema.yaml (referenced by `core/README.md` as *the* core schema). Top-level keys: `$schema`, `required`, `collection`, `properties` — exactly matches the metaschema's allowed set, no `$id`/`$comment`. Validated live: `vec validate-schema` → `VALID`.
2. `vecorel-example-administrative-division-extension.yaml` — a real extension schema, fetched from https://github.com/vecorel/administrative-division-extension/blob/main/schema/schema.yaml. Also validated live → `VALID`. Demonstrates the colon-prefix namespacing convention (`admin:country_code`).
3. `sdl-metaschema-v0.2.0.json` — the SDL metaschema itself (JSON, as it must be — it's a JSON Schema 2020-12 document), fetched from https://vecorel.org/sdl/v0.2.0/schema.json.

Also saved as supporting raw-doc evidence (not SDL documents themselves, but primary sources quoted above): `sdl-readme.md`, `sdl-datatypes.md`, `core-readme.md`, `geoparquet-encoding-readme.md`, `ext-admin-readme.md`.

Both real example SDL documents are flat/shallow: no more than one level of `object`-typed property nesting was observed in either — consistent with the Q2 finding that deep/recursive nesting has to be hand-inlined and real authors apparently keep it shallow.

---

## Q7. Top-level `patternProperties: {"^$": ...}` vs `additionalProperties:false` — RESOLVED, confirmed live as an upstream defect

The metaschema (https://vecorel.org/sdl/v0.2.0/schema.json), top-level, verbatim:
```json
"patternProperties": {
  "^$": {
    "description": "Allow $id, $comments and similar meta properties."
  }
},
"additionalProperties": false,
```
`^$` matches only the literal empty-string key (`""`), never `"$id"` or `"$comment"` — so despite the stated intent in the `description`, this pattern **cannot** admit `$id`/`$comment` as written. It is a regex bug (almost certainly meant to be something like `^\$` to match any key starting with `$`).

**Verified against real behavior, two ways:**

1. **Static**: neither real example document found (core schema, admin-division extension) carries a top-level `$id` or `$comment` — so no real-world document currently exercises this path either way.
2. **Live/dynamic — decisive test.** Constructed a minimal synthetic SDL document with a top-level `$id`:
   ```yaml
   $schema: https://vecorel.org/sdl/v0.2.0/schema.json
   $id: https://example.com/test-extension/schema.yaml
   required: [foo]
   properties:
     foo: {type: string}
   ```
   Ran `uvx --from vecorel-cli vec validate-schema test-toplevel-id.yaml` (vecorel-cli v0.2.15, default metaschema = the real published one, no local overrides). Result: **INVALID**, with jsonschema's own error:
   ```
   - '$id' does not match any of the regexes: '^$'
     Failed validating 'additionalProperties' in schema: ...
   ```
   This confirms the reading exactly: the reference CLI, using the real published metaschema with no relaxation, **rejects** a top-level `$id` outright.

**Does any tooling relax it?** No relaxation found — `vec validate-schema` uses the standard `jsonschema` Python library against the metaschema exactly as published (no special-casing of `$id`/`$comment` in `vecorel_cli/validate_schema.py`). Interestingly, the CLI's *own* internal schema-loading code (`vecorel_cli/vecorel/schemas.py`, `VecorelSchema.__init__`) does `self["$id"] = identifier` after loading a schema into memory — i.e. the tool itself relies on `$id` being a legitimate, settable property on a `VecorelSchema` object at runtime (and `merge_all` explicitly `.pop("$id", None)`s it before merging) — but this is done to the **in-memory Python dict**, not to an on-disk SDL document that then gets round-tripped through `validate-schema`. So the codebase's own conventions assume `$id` is meaningful on a Vecorel schema, while its own validator rejects a file that actually declares one. This is inconsistent and, as written, a probable upstream metaschema defect — not something the spike should silently work around (e.g. by embedding provenance/version info via a non-`$`-prefixed custom key instead of `$id`/`$comment` if that's needed, until upstream fixes the regex).

Source: https://vecorel.org/sdl/v0.2.0/schema.json (fetched, saved as `sdl-metaschema-v0.2.0.json`); live test via `vecorel-cli` v0.2.15 (`uvx --from vecorel-cli vec validate-schema`), test file `test-toplevel-id.yaml` saved in scratchpad; `vecorel_cli/vecorel/schemas.py` (installed package, inspected locally).

---

## Bonus / not asked but relevant to codegen spike

- **Provenance**: Vecorel is the generalized successor to/generalization of **fiboa** ("Field Boundaries for Agriculture", https://github.com/fiboa/specification, https://fiboa.org/) — fiboa is now positioned as an extension built on the Vecorel core (per web search synthesis; not independently verified against a fiboa/vecorel migration doc — mark this sub-point UNVERIFIED, low-stakes for the spike but useful search-context: much of the ecosystem's history/examples/tooling maturity predates the `vecorel` org rename, so searches for "fiboa-cli" / "fiboa validate" surface older but structurally identical prior art).
- `vec validate-schema` exit code does not appear to reflect validity (see Q5 caveat) — worth a smoke-test before relying on it in an automated pipeline.
