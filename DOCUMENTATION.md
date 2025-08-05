# Documentation Generation Strategy

This document outlines the approach for generating user-friendly documentation from Pydantic schema models, designed for tabular data users rather than Python developers.

## Target Audience

**Primary**: Data analysts and engineers working with cloud-hosted Overture Maps datasets using tools like DuckDB, Trino, or Spark to query Parquet files remotely. They think in terms of **datasets** and **columns**, not Python classes.

**Secondary**: Schema extension developers who need to understand the underlying model structure.

## Core Principles

### 1. Dataset-First Organization

- Structure documentation around **themes** → **datasets** → **table schemas**
- Each top-level Pydantic model (e.g., `Division`, `Building`, `TransportationSegment`) represents a queryable dataset
- Focus on "what datasets exist" before "what fields exist"

### 2. Tabular Mental Model

- Present flattened column schemas that match actual cloud-hosted Parquet structure
- Show platform-specific SQL types with interactive dialect selection
- Include cloud-native query examples (DuckDB, Trino, Spark) with realistic use cases
- Use JSON examples as conceptual aids for web developers to understand data relationships

### 3. Progressive Disclosure for Complex Structures

- Start with high-level table schema
- Allow drilling down into complex nested structures
- Provide dedicated documentation for deeply nested rule-based systems

## Key Insight: Cloud-Native Data Access

**Reality of Data Distribution:**

- Overture Maps data is distributed as **cloud-hosted Parquet files**
- Users query remotely using cloud-native tools (no downloading required)
- Data structure is **flattened** for analytical performance
- This differs from the hierarchical structure described in JSON Schema documentation

**Role of JSON in Documentation:**

- JSON examples serve as **conceptual aids** for understanding data relationships
- Help **web developers** bridge from familiar JSON concepts to SQL/Parquet
- Show **logical structure** that gets flattened in actual Parquet files
- **Not** a primary data distribution format

**Mental Model Education Challenge:**

- Traditional GIS users expect **file-exchange patterns** (download, analyze locally)
- Overture promotes **infrastructure patterns** (query remotely, get what you need)
- Documentation must demonstrate **practical advantages** without alienating traditional workflows
- Success requires showing immediate value, not just technical superiority
- Similar to evolution from CSV dumps to database connections in traditional data

## Architecture Approach

### Inspired by spark_generator.py Patterns

The documentation generator follows successful patterns from the existing Spark code generator:

1. **Pydantic as IR**: Leverage Pydantic's rich introspection (`model_fields`, type annotations) rather than AST parsing
2. **Jinja2 templating**: Clean separation between logic and output format
3. **Type mapping system**: Convert Python types to target representations (SQL types instead of Scala)
4. **Batch processing**: Collect all models before generating interconnected documentation

### Key Components

```python
class DatasetDocumentationGenerator:
    """Generate dataset-focused MDX docs for tabular data users."""

    def generate_theme_overview(self, theme_name: str, top_level_models: list[BaseModel]) -> str:
        """Generate theme page listing all available datasets"""

    def generate_dataset_schema(self, model_class: BaseModel) -> str:
        """Generate complete tabular schema for a dataset (top-level model)"""

    def flatten_model_to_columns(self, model_class: BaseModel, prefix: str = "") -> list[ColumnSpec]:
        """Flatten nested Pydantic model into tabular column list"""

    def generate_sql_examples(self, model_class: BaseModel, columns: list[ColumnSpec]) -> str:
        """Generate DuckDB/Trino sample queries for the dataset"""
```

## Documentation Structure

### Theme Level (`/themes/divisions.mdx`)

```markdown
# Divisions Theme

Administrative and political boundaries datasets.

## Available Datasets

| Dataset | Description | Typical Use Cases |
|---------|-------------|-------------------|
| [Division](/datasets/division) | Political boundaries | Geospatial analysis |
| [DivisionArea](/datasets/division-area) | Calculated areas | Territory size analysis |
```

### Dataset Level (`/datasets/transportation-segment.mdx`)

```markdown
# Transportation Segment Dataset

Linear transportation infrastructure (roads, rails, waterways).

## Table Schema

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `id` | VARCHAR | ✓ | Unique identifier |
| `geometry` | GEOMETRY | ✓ | LineString geometry |
| `subtype` | VARCHAR | ✓ | road, rail, or water |
| `speed_limits` | ARRAY<STRUCT> | | Speed limit rules | [📋 Details](#speed-limits) |

## DuckDB Examples

```sql
-- Find highways with variable speed limits
SELECT id, speed_limits
FROM transportation_segments
WHERE subtype = 'road'
  AND list_contains(speed_limits, x -> x.is_max_speed_variable = true);
```

## Sample Data

```json
{
  "id": "segment_123",
  "subtype": "road",
  "speed_limits": [
    {"max_speed": 65, "between": [0.0, 0.8]},
    {"max_speed": 45, "between": [0.8, 1.0]}
  ]
}
```

```

## Handling Complex Nested Structures

For deeply nested structures (like transportation rules), use progressive disclosure:

### 1. Progressive Disclosure Table
Start with high-level columns, allow drilling down:
- Main table shows `speed_limits: ARRAY<STRUCT>`
- Click to expand shows the full `SpeedLimitRule` structure
- Include linear referencing explanation (0.0-1.0 along segment)

### 2. Interactive Schema Browser
Use collapsible MDX components:
```jsx
<SchemaField name="speed_limits" type="ARRAY<SpeedLimitRule>">
  <Description>Speed limit rules for different portions of the road</Description>
  <NestedStructure>
    <SchemaField name="max_speed" type="INTEGER" optional />
    <SchemaField name="between" type="DOUBLE[2]" />
  </NestedStructure>
  <SqlExample>...</SqlExample>
</SchemaField>
```

### 3. Visual Schema Diagrams

Show hierarchical relationships:

```
TransportationSegment
├── Basic Properties (id, geometry, subtype)
├── Road-specific (when subtype = 'road')
│   ├── speed_limits (ARRAY<SpeedLimitRule>)
│   │   ├── max_speed: INTEGER
│   │   └── between: DOUBLE[2]
│   └── access_restrictions (ARRAY<AccessRestrictionRule>)
```

## Navigation Patterns

Users need different levels of detail:

1. **Dataset Overview**: "What columns exist in transportation segments?"
2. **Field Deep-dive**: "How do speed_limits work exactly?"
3. **SQL Examples**: "How do I query segments with variable speed limits?"

**Proposed Navigation:**

- Main dataset page shows flattened SQL-friendly view
- Complex fields get dedicated sub-pages (`/datasets/transportation-segment/speed-limits`)
- Cross-references link related concepts

## Type Mapping Strategy

Convert Pydantic types to platform-appropriate representations with interactive dialect selection:

### Platform-Specific Type Mapping

| Pydantic Type | DuckDB | Trino | Spark | JSON (conceptual) | Notes |
|---------------|--------|-------|-------|-------------------|-------|
| `str` | `VARCHAR` | `VARCHAR` | `STRING` | `string` | Text values |
| `int` | `BIGINT` | `BIGINT` | `LONG` | `number` | Large integers preferred |
| `list[T]` | `T[]` | `ARRAY<T>` | `ARRAY<T>` | `array of T` | Platform-specific syntax |
| `dict[str, T]` | `MAP<VARCHAR, T>` | `MAP<VARCHAR, T>` | `MAP<STRING, T>` | `{key: T}` | Key-value mappings |
| `Optional[T]` | `T` (nullable) | `T` (nullable) | `T` (nullable) | `T \| null` | Nullability separate column |
| `BaseModel` | `STRUCT<...>` | `ROW<...>` | `STRUCT<...>` | `{field: type, ...}` | Nested objects |
| `Enum` | `VARCHAR` | `VARCHAR` | `STRING` | `string` | Include valid values |
| **`bbox`** | **`STRUCT<minx: DOUBLE, miny: DOUBLE, maxx: DOUBLE, maxy: DOUBLE>`** | **`ROW<minx DOUBLE, miny DOUBLE, maxx DOUBLE, maxy DOUBLE>`** | **`STRUCT<minx: DOUBLE, miny: DOUBLE, maxx: DOUBLE, maxy: DOUBLE>`** | **`[number, number, number, number]`** | **Named fields (SQL) vs array (JSON)** |

### Platform Notes

- **DuckDB**: Optimized for local/edge analytics, efficient array handling
- **Trino**: Distributed queries, ROW types for complex structures
- **Spark**: Big data processing, STRUCT types and LONG integers
- **JSON**: Conceptual aid showing logical relationships, not actual data format
- **jq**: Include jq examples for JSON structure manipulation

## Demonstrating Practical Value

### For Traditional GIS Users

**Instead of:** "Download the global roads shapefile (500GB) to find variable speed limits"
**Show:**

```sql
-- Get just the data you need in 30 seconds
SELECT id, names_primary, speed_limits, geometry
FROM 's3://overturemaps.../transportation/segment/*'
WHERE subtype = 'road'
  AND list_contains(speed_limits, x -> x.is_max_speed_variable = true)
  AND ST_Intersects(geometry, ST_GeomFromText('POLYGON(...)'))
```

**Benefits shown, not told:**

- Query terabytes without downloading anything
- Get exactly the subset you need
- Combine spatial and attribute filters efficiently
- Results available in GeoJSON, Shapefile, or any format
- **Geographic filtering is 100x faster** using bbox predicate pushdown

### The `bbox` Column: A Key Performance Feature

Every Overture feature includes a `bbox` column for **fast geographic filtering**:

| Column | Type | Purpose | Example |
|--------|------|---------|---------|
| `bbox` | STRUCT<minx: DOUBLE, miny: DOUBLE, maxx: DOUBLE, maxy: DOUBLE> (Parquet) / ARRAY<DOUBLE> (JSON) | Enables predicate pushdown for spatial queries | `{minx: -74.1, miny: 40.6, maxx: -73.9, maxy: 40.8}` (Parquet) / `[-74.1, 40.6, -73.9, 40.8]` (GeoJSON) |

**Why This Exists:**

- WKB geometry format doesn't include envelope metadata
- Query engines can't do spatial filtering without parsing full geometries
- `bbox` provides rectangular bounds that enable **100x faster** geographic queries
- Essential for **partition pruning** when data is geographically organized

**Performance Comparison:**

```sql
-- FAST: Uses bbox for predicate pushdown (seconds)
SELECT id, names_primary FROM buildings
WHERE bbox.minx >= -74.0 AND bbox.maxx <= -73.5
  AND bbox.miny >= 40.7 AND bbox.maxy <= 40.9

-- SLOW: Requires parsing full geometry (minutes)
SELECT id, names_primary FROM buildings
WHERE ST_Intersects(geometry, ST_MakeEnvelope(-74.0, 40.7, -73.5, 40.9))

-- OPTIMAL: Two-stage filtering (fast + precise)
SELECT id, names_primary, geometry FROM buildings
WHERE bbox.minx >= -74.0 AND bbox.maxx <= -73.5    -- Fast rectangular filter
  AND bbox.miny >= 40.7 AND bbox.maxy <= 40.9      -- Fast rectangular filter
  AND ST_Intersects(geometry, your_precise_polygon) -- Precise spatial filter
```

**Format Notes:**

- **Parquet format**: Named fields (`{minx: -74.1, miny: 40.6, maxx: -73.9, maxy: 40.8}`) for efficient predicate pushdown
- **GeoJSON format**: 4-element array (`[-74.1, 40.6, -73.9, 40.8]`) following GeoJSON specification
- Both formats enable the same performance optimizations but use different representations

### Documentation Strategy

- Lead with **immediate practical examples**, not abstract concepts
- Show **familiar workflows** (finding data, filtering, exporting) with new tools
- Demonstrate **time/storage savings** through realistic scenarios
- Bridge to new concepts after showing value
- **Emphasize performance optimizations** like bbox that make cloud-scale querying practical

## Implementation Priority

1. **Theme overview pages** - Help users discover available datasets
2. **Basic dataset schemas** - Core table structure with SQL examples
3. **Complex field documentation** - Progressive disclosure for nested structures
4. **Cross-references** - Link related types and show usage patterns
5. **Interactive components** - Collapsible schema browser, visual diagrams

## Tools and Dependencies

- **Pydantic**: Model introspection via `model_fields`
- **Jinja2**: Template engine for MDX generation
- **MDX/Docusaurus**: Documentation framework with interactive components
- **Type mapping system**: Convert Python → SQL types for target audience

This approach creates documentation that serves tabular data users while preserving access to the rich structural information needed for schema extension development.
