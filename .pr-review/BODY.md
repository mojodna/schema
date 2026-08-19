Closes #659. Supersedes #660, which is where this change and its changelog wording originated; @Rachmanin0xFF is credited as co-author on the commit.

## Problem

`overture-schema-pyspark` declared `pyspark>=3.4` as a hard dependency, so installing the package resolved `pyspark` on every runtime — including ones (Glue, EMR) that already bundle their own PySpark and shouldn't have this package re-resolving a different version underneath them.

## Change

`pyspark` moves to an optional extra:

```toml
[project.optional-dependencies]
spark = ["pyspark>=3.4"]
```

`pip install overture-schema-pyspark` now resolves cleanly against a runtime-provided PySpark. Standalone environments building their own install `overture-schema-pyspark[spark]`.

That makes "PySpark isn't here" an expected first-run state rather than a broken install, so the package says what to do about it. `overture/schema/pyspark/__init__.py` probes for pyspark before its own imports:

```python
if importlib.util.find_spec("pyspark") is None:
    raise ModuleNotFoundError(
        "overture-schema-pyspark requires PySpark, which isn't installed. "
        "Install it with `pip install overture-schema-pyspark[spark]`, or run "
        "in an environment that already provides PySpark (e.g. a Spark cluster)."
    )
```

Two properties are worth stating, because they're what make one probe sufficient:

**It covers every entry path.** `overture/schema/pyspark/__init__.py` is a real `__init__.py` — only `overture` and `overture.schema` are PEP 420 namespaces — so it executes on any import of any submodule, including the 15 generated expression modules that import `pyspark.sql` directly. Guarding at those import sites instead would mean 22 guards (7 hand-written modules plus the generated tree, which would need a renderer change), of which only one is ever reachable: the re-export chain always hits `check.py` first.

**It catches nothing.** A `try`/`except ModuleNotFoundError` around the imports would also swallow an unrelated missing dependency, and — less obviously — would misreport an installed-but-broken pyspark. With `py4j` removed, `import pyspark` raises `ModuleNotFoundError(name='py4j')`; an `except` clause reports "PySpark isn't installed", which is false, and avoiding that requires inspecting `e.name`. The probe has no such branch: it asks whether pyspark is findable, and everything else surfaces its own real error from the imports that follow.

### The version floor

The extra still carries `>=3.4` — the specifier rides the requirement, and `overture-schema-pyspark[spark]` alongside `pyspark==3.3.4` resolves as unsatisfiable. The bare install is where it stops binding, which is the path this PR opens: nothing there declares `pyspark`, so no resolver ever sees the floor. `__init__.py` checks it against the PySpark that actually turned up:

```python
import pyspark

if _problem := pyspark_version_problem(getattr(pyspark, "__version__", None)):
    raise ImportError(_problem)
```

The floor is read back out of this distribution's own `Requires-Dist` metadata rather than restated in code, so `pyproject.toml` stays the single declaration and the check cannot drift from it. The installed version comes from `pyspark.__version__` rather than PySpark's metadata, because a PySpark supplied by a Spark distribution sits on `sys.path` with no `dist-info` to read — precisely the environment the check exists for.

Two states leave nothing to judge and pass: a PySpark reporting no version, and a source tree with no installed metadata. A third would fail open the same silent way — a distribution name that stopped resolving — so a test pins that the lookup finds real metadata. Prereleases satisfy the floor, since Spark ships release candidates and dev builds. The cost is a `packaging` dependency, for requirement and version parsing.

## Tests

`tests/test_optional_pyspark.py` holds eight tests. Three are gates, each failing against the unguarded code and passing with it: `test_missing_pyspark_names_the_extra` for the probe, `test_pyspark_below_the_declared_floor_names_both_versions` for the floor, and `test_the_floor_is_read_from_package_metadata` for reading the floor rather than restating it — a guard carrying its own copy of `3.4` passes the second and fails the third, verified against that implementation.

The other five are controls that pass before and after. `test_unrelated_missing_dependency_surfaces_its_own_error` pins the no-masking property (verified to fail against a broad-`except` implementation). `test_unreadable_package_metadata_does_not_block_import` and `test_pyspark_without_a_reported_version_does_not_block_import` pin the two states that leave nothing to judge. `test_the_declared_floor_is_readable_here` pins that the metadata lookup is live; against a misspelled distribution name it fails alongside the floor gate, naming the cause instead of leaving a silent no-op to diagnose. And `test_package_imports_when_pyspark_is_installed` pins the normal path.

The two blocking mechanisms differ on purpose. The pyspark test sets `sys.modules["pyspark"] = None`, which makes `find_spec` return `None` — the same signal real absence produces at the seam this code reads. The unrelated-dependency test uses a `meta_path` finder that raises `ModuleNotFoundError(..., name=...)`, because `sys.modules[x] = None` raises `ImportError` instead, and a control built on it would pass under the very implementation it exists to forbid.

## Verified

- `make check TESTMON=` — 6206 passed.
- Wheel install in a clean venv, no extra, with a stand-in `pyspark` on `PYTHONPATH`: 3.3.4 raises the floor message naming both versions; 3.4, 3.4.0, 4.1.0.dev1 and 9.9.9 clear the guard and go on to fail on the stand-in's missing `pyspark.sql`, which is the real import running.
- The resolver still enforces the extra: `overture-schema-pyspark[spark]` with `pyspark==3.3.4` is unsatisfiable, while the same pin without the extra resolves clean — the gap the import check covers.
- Bare install in a clean venv (`uv pip install ./packages/overture-schema-system ./packages/overture-schema-pyspark`, no pyspark): importing the package raises the actionable message; the automated test pins the branch, this pins that `find_spec` is the right question.
- Same venv with `shapely` also removed, and the worktree venv with `py4j` removed: both surface their own errors, unmasked.
- `uv lock --check` accepts the lockfile, which gains only the two `packaging` edges; CI's `make check` installs all extras, so coverage is unaffected.
- No other package in this repo depends on `overture-schema-pyspark` or imports `pyspark`.
