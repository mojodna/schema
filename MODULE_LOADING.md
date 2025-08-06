# Module Loading Mechanism and Future Requirements

## Current Implementation

The CLI currently supports explicit module loading via:

```bash
uv run codegen generate --model "overture.schema.buildings.building.models:Building"
```

### How It Works

1. **uv Workspace Environment**: When `uv run codegen` executes:
   - uv installs all workspace packages (`packages/*`) in development mode
   - Each package's `src/` directory is added to `sys.path`
   - Packages become importable via standard Python import mechanisms

2. **Module Resolution Chain**:

   ```python
   # In _load_model_class():
   module = importlib.import_module("overture.schema.buildings.building.models")
   model_class = getattr(module, "Building")
   ```

3. **sys.path Contents** (under `uv run`):

   ```
   /path/to/packages/overture-schema-buildings-theme/src
   /path/to/packages/overture-schema-core/src
   /path/to/packages/overture-schema-validation/src
   # ... all other workspace packages
   ```

4. **Package Structure**:

   ```
   packages/overture-schema-buildings-theme/src/
   └── overture/
       └── schema/
           └── buildings/
               └── building/
                   └── models.py  # Contains Building class
   ```

### Why It Works in Development

- **Workspace Dependencies**: Each package declares `workspace = true` dependencies
- **Namespace Packages**: `overture.*` packages use namespace packaging
- **Development Mode**: All packages installed as editable (`-e` equivalent)
- **Unified sys.path**: All source directories available simultaneously

## Future Requirements: Arbitrary Directory Support

### Goal

Support loading models from arbitrary directories not in the current workspace:

```bash
codegen generate --model "/path/to/custom/models.py:MyModel"
codegen generate --model-dir "/path/to/custom/models/" --model "models:MyModel"
```

### Challenges

1. **Dependency Resolution**: Custom models may depend on:
   - Standard Overture packages (`overture-schema-core`, `overture-schema-validation`)
   - Third-party packages (`pydantic`, custom validators)
   - Other custom modules in the same directory

2. **Runtime sys.path Manipulation**:

   ```python
   # Need to add both the target directory and its dependencies
   sys.path.insert(0, "/path/to/custom/models/")
   sys.path.insert(0, "/path/to/overture-schema-core/src/")
   # ... ensure all dependencies are available
   ```

3. **Import Context Isolation**: Avoid polluting global import namespace

### Implementation Strategy

#### Option 1: Dynamic sys.path Management

```python
def load_model_from_path(file_path: str, class_name: str) -> type[BaseModel]:
    """Load model from arbitrary file path with dependency resolution."""
    import sys
    from pathlib import Path

    model_dir = Path(file_path).parent
    original_path = sys.path.copy()

    try:
        # Add model directory
        sys.path.insert(0, str(model_dir))

        # Discover and add dependency directories
        deps = discover_model_dependencies(file_path)
        for dep_path in deps:
            sys.path.insert(0, str(dep_path))

        # Import using module name derived from file path
        module_name = Path(file_path).stem
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return getattr(module, class_name)
    finally:
        # Restore original sys.path
        sys.path[:] = original_path
```

#### Option 2: Virtual Environment Creation

```python
def load_model_with_venv(file_path: str, class_name: str) -> type[BaseModel]:
    """Create temporary environment with proper dependencies."""
    # 1. Analyze dependencies in the target file
    # 2. Create temporary venv with required packages
    # 3. Execute import in that environment
    # 4. Serialize/pickle the class back to main process
```

#### Option 3: Module Spec Loading (Recommended)

```python
def load_model_from_file(file_path: str, class_name: str) -> type[BaseModel]:
    """Load model using importlib.util for isolated loading."""
    import importlib.util
    from pathlib import Path

    # Add directory to path temporarily
    model_dir = Path(file_path).parent
    with temporary_path_addition(model_dir):
        # Load dependencies first
        ensure_dependencies_available(file_path)

        # Load the target module
        spec = importlib.util.spec_from_file_location(
            f"custom_model_{Path(file_path).stem}",
            file_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        return getattr(module, class_name)
```

### Dependency Discovery

Need to implement dependency analysis:

```python
def discover_model_dependencies(file_path: str) -> list[Path]:
    """Analyze Python file to discover required dependencies."""
    import ast

    with open(file_path) as f:
        tree = ast.parse(f.read())

    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    # Map imports to filesystem paths
    dependency_paths = []
    for imp in imports:
        if imp.startswith('overture.'):
            # Find corresponding workspace package
            path = find_overture_package_path(imp)
            if path:
                dependency_paths.append(path)

    return dependency_paths
```

### CLI Interface Extensions

```bash
# File-based loading
codegen generate --model-file "/path/to/models.py:MyModel"

# Directory-based loading
codegen generate --model-dir "/path/to/models/" --model "module_name:ClassName"

# With explicit dependency paths
codegen generate --model-file "/path/to/models.py:MyModel" \
                  --dependency-path "/path/to/overture-core/src" \
                  --dependency-path "/path/to/custom-validators"

# Auto-discovery in directory
codegen generate --discover-in "/path/to/custom/models/"
```

### Context Managers for Clean Implementation

```python
@contextmanager
def temporary_path_addition(*paths):
    """Temporarily add paths to sys.path."""
    import sys
    original_path = sys.path.copy()
    try:
        for path in reversed(paths):  # Insert in reverse order
            sys.path.insert(0, str(path))
        yield
    finally:
        sys.path[:] = original_path

@contextmanager
def isolated_import_context(base_dir: Path):
    """Create isolated context for importing custom models."""
    deps = discover_model_dependencies(base_dir)
    with temporary_path_addition(base_dir, *deps):
        yield
```

## Implementation Priority

1. **Phase 1**: Basic file-based loading with manual dependency specification
2. **Phase 2**: Automatic dependency discovery for common patterns
3. **Phase 3**: Full directory scanning and model discovery
4. **Phase 4**: Virtual environment isolation for complex dependency scenarios

## Related Code Locations

- Current implementation: `packages/overture-schema-codegen/src/overture/schema/codegen/cli.py:_load_model_class()`
- Discovery mechanism: `packages/overture-schema-core/src/overture/schema/core/discovery.py`
- Workspace configuration: `pyproject.toml` and `packages/*/pyproject.toml`
