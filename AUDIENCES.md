# Project Audiences

This document defines the distinct user groups for the Overture Maps Pydantic schema project and their specific needs.

## Primary Audience: Tabular Data Users

### Who They Are

- **Data analysts and engineers** working with Overture Maps datasets
- Use cloud-native tools: DuckDB, Trino, Spark to query remote Parquet files
- Work with large-scale columnar data without downloading (cloud-native analysis)
- Background in SQL, data analysis, and geospatial processing

- **GIS professionals and geographers** working with spatial datasets
- Traditional background with Shapefiles, GeoJSON, and desktop GIS tools (QGIS, ArcGIS)
- Increasingly using cloud-native GeoParquet for large-scale spatial analysis
- Background in spatial analysis, cartography, and geographic data modeling

### Mental Model

**Data Analysts:**

- Think in terms of **datasets** and **tables**, not Python classes
- Focus on **columns**, **types**, and **queryable schemas**
- Want to understand "what data is available" and "how to query it"
- Care about data formats: Cloud-native Parquet access, SQL compatibility

**GIS Users:**

- Think in terms of **feature classes** and **attribute tables**
- Focus on **geometry types**, **coordinate systems**, and **spatial relationships**
- Want to understand "what geographic data exists" and "how it relates spatially"
- Care about data formats: GeoJSON export workflows, cloud-native spatial analysis
- **Transitioning from file-exchange to infrastructure mindset**: Moving from "download and analyze" to "query what you need"

### Key Needs

**Common to Both:**

- **Dataset discovery**: "What datasets exist in the divisions theme?"
- **Schema reference**: "What columns/attributes are available?"
- **Practical examples**: Sample data, realistic use cases

**Data Analyst Specific:**

- **SQL examples**: "How do I query roads with variable speed limits?"
- **Type mappings**: Understanding Python types → SQL types (VARCHAR, BIGINT, ARRAY<STRUCT>)
- **Performance considerations**: Indexing, partitioning, query optimization

**GIS User Specific:**

- **Geometry examples**: "How do I export building polygons to GeoJSON?"
- **Spatial queries**: "How do I find all roads within a city boundary?"
- **Format conversions**: Cloud Parquet → GeoJSON export → desktop GIS workflows
- **Coordinate systems**: Understanding geometry storage and projections

### What They DON'T Need

- Python implementation details
- Pydantic-specific concepts (validators, model inheritance)
- Individual type documentation for sub-components
- Code generation patterns

## Secondary Audience: Schema Extension Developers

### Who They Are

- Developers building custom schemas on top of Overture base types
- Creating domain-specific extensions (e.g., retail locations, transit systems)
- Need to understand the underlying Pydantic model structure
- Python developers familiar with type systems and validation

### Mental Model

- Think in terms of **types**, **inheritance**, and **composition**
- Focus on **extensibility patterns** and **validation rules**
- Want to understand "how types relate" and "what can be extended"
- Care about implementation: Python classes, validation constraints, JSON Schema generation
- May approach **conditional subclasses** from different angles:
  - **Object-oriented background**: Start with base classes, add discriminated union types
  - **Data modeling background**: Start with union types, factor out common properties

### Key Needs

- **Type hierarchy**: How models inherit and compose
- **Extension patterns**: Adding new fields, types, enum values, validation rules
- **Composition patterns**: Building complex types from simpler components
- **Discriminated union patterns**: Conditional subclasses using `Annotated[Union[A, B], Field(discriminator="field")]`
- **Validation system**: Custom constraints, validation mixins
- **Code examples**: How to extend existing models properly
- **Implementation details**: Pydantic specifics, registration system, JSON Schema export

### Overlap Areas

Both audiences benefit from:

- **Cross-references**: Understanding how types are used across themes
- **Validation rules**: Business logic constraints (human-readable for analysts, implementation details for developers)
- **Examples**: Sample data (realistic for analysts, extension patterns for developers)

## Key Insight: Data Access vs Structure Understanding

**Reality of Data Access:**

- Users query **cloud-hosted Parquet files** directly using tools like DuckDB, Trino, Spark
- No downloading required due to cloud-native columnar formats
- Data is **flattened** for analytical performance, different from hierarchical JSON Schema documentation

**Role of JSON Examples:**

- JSON serves as a **conceptual aid** for understanding data structure
- Helps **web developers** bridge from familiar JSON to unfamiliar SQL/Parquet concepts
- Shows **logical relationships** between fields that are flattened in actual Parquet
- **Not** a primary data distribution format

**Mental Model Transition Challenge:**

- Many GIS users expect **file-exchange workflows** ("download shapefile, analyze locally")
- Overture represents **infrastructure approach** ("query cloud dataset, get what you need")
- Documentation must bridge this gap without alienating traditional GIS users
- Similar transition that happened in traditional data: CSV dumps → database connections
- Success depends on showing **practical value** of query-first approach, not just technical superiority

## Documentation Strategy Implications

### For Tabular Data Users (Primary)

**Data Analysts:**

- **Entry point**: Theme overviews → Dataset schemas → SQL examples
- **Format**: MDX with interactive tables, collapsible sections for complex fields
- **Language**: SQL-native types, business terminology, practical use cases
- **Structure**: Flattened schemas showing actual cloud Parquet column structure

**GIS Users:**

- **Entry point**: Theme overviews → Feature class schemas → Geometry examples
- **Format**: MDX with spatial examples, coordinate system references, format conversion guides
- **Language**: GIS terminology (feature classes, attributes, geometries), spatial concepts
- **Structure**: Geometry-focused schemas with cloud-to-local export examples (GeoJSON, Shapefile)
- **Mental model bridging**: Show familiar concepts (feature classes) mapped to cloud infrastructure (queryable datasets)

### For Schema Extension Developers (Secondary)

- **Entry point**: Type references → Extension patterns → Implementation guides
- **Format**: Traditional API documentation with code examples
- **Language**: Python types, Pydantic concepts, technical terminology
- **Structure**: Hierarchical type documentation with inheritance details

### Shared Resources

- **Cross-references**: Link between dataset columns and underlying types
- **Validation documentation**: Business rules (for analysts) with implementation notes (for developers)
- **Progressive disclosure**: Start with tabular view, allow drilling into technical details

## Design Decisions

### Primary Audience First

- Main navigation organized around **themes** and **datasets**
- Landing pages focus on **data discovery** and **SQL querying**
- Technical implementation details are secondary/linked

### Avoid Audience Confusion

- Separate entry points prevent overwhelming tabular users with Python details
- Clear labeling: "For Data Analysis" vs "For Schema Development"
- Progressive disclosure allows drilling down without cluttering main views

### Leverage Existing Patterns

- Follow successful patterns from other data documentation (BigQuery docs, dbt docs)
- Use familiar SQL concepts rather than introducing new abstractions
- Provide realistic examples that match actual use cases

This audience-first approach ensures the documentation serves its primary users effectively while still supporting the technical needs of schema extension developers.
