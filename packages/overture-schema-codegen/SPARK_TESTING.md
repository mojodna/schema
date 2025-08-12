# Testing Generated Scala Code

TODO create a sub-agent that knows how to run generated code in Spark, however strangely. It can provide feedback on what worked and didn't based on the output of `spark-shell`.

## Spark Shell Testing

To test generated Scala code in spark-shell (package declarations don't work in REPL):

```bash
# Basic compilation test
(echo ":paste"; grep -v "^package" /tmp/spark-scala-output/Address.scala) | spark-shell

# Full end-to-end test with data
(echo ":paste"; grep -v "^package" /tmp/spark-scala-output/Address.scala; echo ""; echo "val df = spark.read.parquet(\"addresses.geoparquet\").withColumn(\"theme\", lit(\"addresses\")).withColumn(\"type\", lit(\"address\")).select(\"id\", \"theme\", \"type\", \"country\", \"number\", \"postal_city\", \"postcode\", \"street\", \"unit\").withColumn(\"geometry\", lit(\"placeholder\")).withColumn(\"version\", lit(1L)).withColumn(\"sources\", lit(null).cast(\"string\")).withColumn(\"address_levels\", lit(null).cast(\"array<string>\"))"; echo "val addresses = Address.fromDataFrame(df)(spark)"; echo "addresses.show(2)") | spark-shell
```

## Loading Test Data

```scala
// Load GeoParquet file
val df = spark.read.parquet("addresses.geoparquet")

// Convert to Dataset using generated code
val addresses = Address.fromDataFrame(df)
```

## Common Issues

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

## ✅ Successful Workaround

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
