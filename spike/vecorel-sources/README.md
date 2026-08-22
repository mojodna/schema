# Vecorel source evidence

Fetched 2026-08-22, and preserved here because `spike/VECOREL_CENSUS.md` makes claims
about Vecorel semantics that are otherwise only checkable by re-fetching upstream — where
the answer may have moved.

- `vecorel-spec-findings.md` — the investigation behind the census's spec claims, each
  with a source URL and a RESOLVED/UNVERIFIED/BLOCKED mark. Load-bearing for the
  nullability result in particular (`nullable == not required`, enforced in
  `vecorel_cli/parquet/types.py` and the GeoParquet validator).
- `vecorel-example-core-schema.yaml`, `vecorel-example-administrative-division-extension.yaml`
  — real published SDL documents. These, not the metaschema, are the ground truth for
  idiom: every SDL document in the wild is YAML.
- `sdl-readme.md`, `sdl-datatypes.md` — the SDL vocabulary and type table.

The metaschema itself is `../vecorel-sdl-metaschema.json`, which the validator reads.
