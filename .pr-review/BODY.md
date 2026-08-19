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

## Tests

`tests/test_optional_pyspark.py` adds three tests. One is the gate: `test_missing_pyspark_names_the_extra` fails against the unguarded `__init__` and passes with the probe. The other two are guards, and pass both before and after — `test_unrelated_missing_dependency_surfaces_its_own_error` pins the no-masking property (verified to fail against a broad-`except` implementation), and `test_package_imports_when_pyspark_is_installed` pins the normal path.

The two blocking mechanisms differ on purpose. The pyspark test sets `sys.modules["pyspark"] = None`, which makes `find_spec` return `None` — the same signal real absence produces at the seam this code reads. The unrelated-dependency test uses a `meta_path` finder that raises `ModuleNotFoundError(..., name=...)`, because `sys.modules[x] = None` raises `ImportError` instead, and a control built on it would pass under the very implementation it exists to forbid.

## Verified

- `make check TESTMON=` — 6201 passed.
- Bare install in a clean venv (`uv pip install ./packages/overture-schema-system ./packages/overture-schema-pyspark`, no pyspark): importing the package raises the actionable message; the automated test pins the branch, this pins that `find_spec` is the right question.
- Same venv with `shapely` also removed, and the worktree venv with `py4j` removed: both surface their own errors, unmasked.
- `uv sync --locked --all-packages --all-extras` accepts the lockfile; CI's `make check` installs all extras, so coverage is unaffected.
- No other package in this repo depends on `overture-schema-pyspark` or imports `pyspark`.
