# Type Aliases for Spark Scala Generation

## What We Learned

The Pydantic type aliases are fully visible through introspection and contain rich metadata:

### Field-Level Detection

Fields show their full `Annotated` types, e.g.:

```
country: typing.Annotated[str, CountryCodeConstraint, Field(description='ISO 3166-1 alpha-2 country code')]
```

### Module-Level Type Aliases Available

Type aliases are accessible as module attributes in:

- `overture.schema.validation.types` - Basic constrained types
- `overture.schema.core.types` - Core domain types
- `overture.schema.transportation.types` - Transportation-specific types
- etc.

### Rich Metadata Available

Each type alias contains:

- Base type (str, int, float, list, dict)
- Constraint objects (CountryCodeConstraint, etc.)
- Field descriptions
- Validation metadata (Ge, Le, MinLen, etc.)

## Implementation Strategy

### 1. Type Alias Detection

```python
def detect_type_aliases(field_info: FieldInfo) -> Optional[str]:
    """Detect if field uses a type alias by matching annotation patterns."""
    # Match annotation structure against known type aliases
    # Return alias name if found
```

### 2. Reverse Mapping

Create a registry mapping `Annotated` type structures to their alias names:

```python
TYPE_ALIAS_REGISTRY = {
    # Map from annotation structure to alias name
    annotation_signature: "CountryCode",
    # etc.
}
```

### 3. Constraint Translation

Map constraint objects to Scala documentation/validation:

```python
CONSTRAINT_MAPPINGS = {
    CountryCodeConstraint: "ISO 3166-1 alpha-2 country code",
    LinearReferenceRangeConstraint: "Range: 0.0 to 1.0",
    # etc.
}
```

### 4. Scala Type Alias Generation

```scala
// Generated type aliases
/** ISO 3166-1 alpha-2 country code */
type CountryCode = String

/** Represents a linearly-referenced position between 0% and 100% of distance along a path */
type LinearlyReferencedPosition = Double  // Range: 0.0 to 1.0

/** Array of access restriction rules (unique items) */
type AccessRules = Array[AccessRestrictionRule]
```

### 5. Dependency Resolution

Type aliases can depend on other type aliases:

- `Id` depends on `NoWhitespaceString`
- `CommonNames` depends on `LanguageTag` and `TrimmedString`
- Need topological sort for generation order

## Examples of What We'd Generate

### Basic Constrained Types

```scala
type PlaceCategory = String  // Pattern constraint
type CountryCode = String    // ISO 3166-1 alpha-2
type HexColor = String       // Hex color format
type ConfidenceScore = Double // Range: 0.0 to 1.0
```

### Collection Types

```scala
type AccessRules = Array[AccessRestrictionRule]  // Unique items
type Routes = Array[RouteReference]
type CommonNames = Map[String, String]  // LanguageTag -> TrimmedString
```

### Complex Types

```scala
type LinearlyReferencedRange = Array[LinearlyReferencedPosition]  // Min length: 2
```

## Integration Points

1. **In `spark_scala.py`**:
   - Add type alias detection to field processing
   - Generate type alias definitions at top of file
   - Use type aliases instead of raw types in case classes

2. **In `introspection.py`**:
   - Extend `FieldInfo` to include detected type alias name
   - Add utility functions for type alias discovery

3. **Module organization**:
   - Generate type aliases in separate "Types.scala" file
   - Import in generated case classes
   - Or include type aliases at top of each generated file

## Complexity Assessment

**Medium-High complexity** due to:

- Need to build type alias registry from runtime inspection
- Complex nested `Annotated` type matching
- Constraint interpretation and mapping
- Dependency resolution between aliases
- Integration with existing generator architecture

**Estimated effort**: 2-3 days for full implementation with proper testing.

## Testing Generated Scala Code

### Spark Shell Testing

To test generated Scala code in spark-shell (package declarations don't work in REPL):

```bash
# Basic compilation test
(echo ":paste"; grep -v "^package" /tmp/spark-scala-output/Address.scala) | spark-shell

# Full end-to-end test with data
(echo ":paste"; grep -v "^package" /tmp/spark-scala-output/Address.scala; echo ""; echo "val df = spark.read.parquet(\"addresses.geoparquet\").withColumn(\"theme\", lit(\"addresses\")).withColumn(\"type\", lit(\"address\")).select(\"id\", \"theme\", \"type\", \"country\", \"number\", \"postal_city\", \"postcode\", \"street\", \"unit\").withColumn(\"geometry\", lit(\"placeholder\")).withColumn(\"version\", lit(1L)).withColumn(\"sources\", lit(null).cast(\"string\")).withColumn(\"address_levels\", lit(null).cast(\"array<string>\"))"; echo "val addresses = Address.fromDataFrame(df)(spark)"; echo "addresses.show(2)") | spark-shell
```

### Loading Test Data

```scala
// Load GeoParquet file
val df = spark.read.parquet("addresses.geoparquet")

// Convert to Dataset using generated code
val addresses = Address.fromDataFrame(df)
```

### Common Issues

**Discovered from addresses.geoparquet testing:**

1. **Missing Fields**: DataFrame missing `theme`, `type` fields that case class expects
2. **Type Mismatches**:
   - `geometry`: `binary` in parquet vs `String` in case class
   - `version`: `integer` vs `Long`
   - `sources`: Complex nested `ARRAY<STRUCT<...>>` vs `Option[String]`
   - `address_levels`: Nested struct vs `Option[Array[String]]`
3. **Extra Fields**: DataFrame has `bbox` field not in case class
4. **SparkSession Import**: Need explicit `(spark)` parameter for `fromDataFrame`

**Specific Error:**

```
Cannot up cast sources from "ARRAY<STRUCT<property: STRING, dataset: STRING, record_id: STRING, update_time: STRING, confidence: DOUBLE, between: ARRAY<DOUBLE>>>" to "STRING"
```

**Root Cause**: Our introspection system flattens nested structures but generates simple Scala types, creating mismatches with actual parquet schema.

### ✅ Successful Workaround

**Working approach with synthetic columns and type casting:**

```scala
val df = spark.read.parquet("addresses.geoparquet")
  .withColumn("theme", lit("addresses"))
  .withColumn("type", lit("address"))
  .select("id", "theme", "type", "country", "number", "postal_city", "postcode", "street", "unit")
  .withColumn("geometry", lit("placeholder"))
  .withColumn("version", lit(1L))
  .withColumn("sources", lit(null).cast("string"))
  .withColumn("address_levels", lit(null).cast("array<string>"))

val addresses = Address.fromDataFrame(df)(spark)
addresses.show(2)  // ✅ Works!
```

**Key insights:**

1. **Partition columns**: Add synthetic `theme`/`type` (would come from partitions in production)
2. **Type casting**: Cast complex nested structures to compatible simple types
3. **Schema alignment**: Ensure DataFrame schema matches generated case class exactly

**Original Issues:**

- Package declarations cause REPL errors
- Column type mismatches between DataFrame and case class
- Complex nested structures may need custom encoders
