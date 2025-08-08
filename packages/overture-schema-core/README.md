# Overture Schema Core

Core Pydantic models and base classes for Overture Maps schemas, providing foundational types, geometry handling, and a comprehensive scoping system for conditional rule application.

## Installation

```bash
pip install overture-schema-core
```

## Key Components

- **Base Classes**: Extensible base models for Overture Maps features
- **Geometry Types**: WKB geometry type hints and utilities
- **Common Structures**: Shared models used across all themes
- **Generic Id Type**: Type-parameterized feature IDs for enhanced type safety
- **Abstract Data Types**: Validated primitive types with multi-target serialization support
- **Scoping System**: Flexible conditional rule application framework

## Generic Id Type

The `Id` type is a generic type that can be optionally parameterized by feature type to provide enhanced type safety and better documentation of what kind of entity an ID refers to.

### Basic Usage

```python
from overture.schema.core.types import Id

# Basic usage (backward compatible)
feature_id: Id = Id("abc123")

# Works with any string value that meets validation requirements
id_value = Id("feature_456")
```

### Type-Parameterized Usage

For enhanced type safety, you can parameterize `Id` with a specific feature type:

```python
from typing import Literal
from overture.schema.core.types import Id

# Type-specific IDs for better type safety
building_id: Id[Literal["building"]] = "building_123"
place_id: Id[Literal["place"]] = "place_456"
connector_id: Id[Literal["connector"]] = "connector_789"
```

### Integration with Feature Models

When defining feature models, you can use parameterized IDs to document the expected ID type:

```python
from typing import Literal
from overture.schema.core import OvertureFeature
from overture.schema.core.types import Id

class Building(OvertureFeature):
    id: Id[Literal["building"]]  # Clearly indicates this is a building ID
    theme: Literal["buildings"]
    type: Literal["building"]
    # ... other fields
```

### Type Safety Benefits

The generic `Id` type provides several advantages:

1. **Enhanced Documentation**: The type parameter serves as documentation about what the ID refers to
2. **Type Checker Support**: Static type checkers can distinguish between different ID types
3. **Backward Compatibility**: Existing code using unparameterized `Id` continues to work unchanged
4. **Runtime Behavior**: All IDs remain strings at runtime with the same validation

### Validation

All `Id` types (parameterized and unparameterized) use the same underlying validation:

- Must be a non-whitespace string
- Minimum length of 1 character
- May be associated with the Global Entity Reference System (GERS) if the feature is part of GERS

### Examples in Context

```python
from typing import Literal
from overture.schema.core.types import Id

def process_building_id(building_id: Id[Literal["building"]]) -> str:
    return f"Processing building: {building_id}"

def process_place_id(place_id: Id[Literal["place"]]) -> str:
    return f"Processing place: {place_id}"

# Type checker can distinguish between these
building = Id("building_123")
place = Id("place_456")

# This works fine
process_building_id(building)
process_place_id(place)

# Type checker would warn about mixing types if you had:
# process_building_id(place)  # Type error with parameterized IDs
```

## Foreign Key Relationships

The generic `Id` type can be extended to create typed foreign key relationships between features. This provides enhanced type safety and enables automatic relationship discovery.

### Creating Foreign Key Types

```python
from typing import Literal
from overture.schema.core.types import Id
from overture.schema.core import ForeignKey, References

# Method 1: Using parameterized Id types
ConnectorId = Id[Literal["connector"]]
SegmentId = Id[Literal["segment"]]
BuildingId = Id[Literal["building"]]

# Method 2: Using the References helper (simpler syntax)
from overture.schema.core import References
ConnectorRef = References(Literal["connector"])

# Method 3: Using ForeignKey with explicit source and target
BuildingPartId = ForeignKey[Literal["building"], Literal["building_part"]]
```

### Using Foreign Keys in Models

```python
from typing import Literal, Annotated
from pydantic import BaseModel, Field
from overture.schema.core.types import Id

# Define foreign key types
ConnectorId = Id[Literal["connector"]]
SegmentId = Id[Literal["segment"]]

class TransportationSegment(BaseModel):
    """A transportation segment with connector references."""

    id: SegmentId
    start_connector: ConnectorId
    end_connector: ConnectorId
    connected_segments: list[SegmentId] = []

class ConnectorReference(BaseModel):
    """Reference to a connector at a specific position."""

    connector_id: ConnectorId
    at_position: Annotated[float, Field(ge=0.0, le=1.0)]
```

### Automatic Relationship Discovery

You can automatically discover relationships in your models:

```python
from overture.schema.core import get_relationships_from_model

# Analyze a model to find its foreign key relationships
relationships = get_relationships_from_model(TransportationSegment)

print("Transportation Segment relationships:")
for field_name, fk_list in relationships.items():
    for fk_info in fk_list:
        print(f"  {field_name}: references {fk_info['target']}")

# Output:
# Transportation Segment relationships:
#   start_connector: references typing.Literal['connector']
#   end_connector: references typing.Literal['connector']
#   connected_segments: references typing.Literal['segment']
```

### JSON Schema Integration

Foreign key relationships are automatically included in JSON Schema generation:

```python
from overture.schema.core.json_schema import json_schema

schema = json_schema(TransportationSegment)

# Foreign key fields include metadata about their relationships
connector_field = schema["properties"]["start_connector"]
print(connector_field.get("x-foreign-key"))  # Relationship metadata
```

### Benefits of Typed Foreign Keys

1. **Type Safety**: Prevents accidentally mixing different ID types
2. **Self-Documenting**: The type annotations clearly show relationships
3. **Tooling Support**: IDEs and linters can provide better assistance
4. **Automatic Discovery**: Relationships can be discovered programmatically
5. **Schema Generation**: Foreign key constraints can be included in generated schemas
6. **Database Integration**: Could be used to generate SQL foreign key constraints

### Real-World Example: Transportation Network

```python
class Connector(BaseModel):
    id: Id[Literal["connector"]]
    geometry: Point
    connected_segments: list[Id[Literal["segment"]]] = []

class Segment(BaseModel):
    id: Id[Literal["segment"]]
    geometry: LineString
    start_connector: Id[Literal["connector"]]
    end_connector: Id[Literal["connector"]]

class Route(BaseModel):
    id: Id[Literal["route"]]
    name: str
    segments: list[Id[Literal["segment"]]]

# The type system ensures you can't accidentally use a segment ID
# where a connector ID is expected, and vice versa
```

This approach enables building strongly-typed, self-documenting data models with explicit relationships while maintaining runtime compatibility with existing code.

## Abstract Data Types

The abstract data types system provides validated primitive types with automatic
constraint checking and multi-target serialization support. This enables consistent type
definitions that can generate appropriate representations for different targets
(Scala, Spark, Parquet, JSON Schema).

### Available Types

#### Integer Types

- **`UInt8`**: 8-bit unsigned integer (0-255)
- **`UInt16`**: 16-bit unsigned integer (0-65535)
- **`UInt32`**: 32-bit unsigned integer (0-4294967295)
- **`Int8`**: 8-bit signed integer (-128 to 127)
- **`Int32`**: 32-bit signed integer (-2³¹ to 2³¹-1)
- **`Int64`**: 64-bit signed integer (-2⁶³ to 2⁶³-1)

#### Floating Point Types

- **`Float32`**: 32-bit floating point number
- **`Float64`**: 64-bit floating point number

### Basic Usage

```python
from pydantic import BaseModel, Field
from overture.schema.core.types.abstract import (
    UInt8, UInt32, Float32
)

class Building(BaseModel):
    """Building feature with abstract data types."""

    height: Float32 | None = Field(
        None,
        description="Height of building in meters"
    )

    num_floors: UInt8 | None = Field(
        None,
        description="Number of floors in building"
    )

    area: UInt32 | None = Field(
        None,
        description="Floor area in square meters"
    )
```

### Automatic Validation

Abstract types automatically validate constraints:

```python
# Valid values
building = Building(height=45.5, num_floors=12, area=2500)

# Invalid values raise ValidationError
Building(num_floors=256)  # Error: 256 > UInt8 maximum (255)
Building(num_floors=-1)   # Error: -1 < UInt8 minimum (0)
```

### Multi-Target Type Mappings

Abstract types can be mapped to different target systems:

```python
from overture.schema.core.types.abstract import Float32, Int32, UInt8, get_target_type

# Scala types
get_target_type(UInt8, "scala")     # "Byte"
get_target_type(Float32, "scala")   # "Float"
get_target_type(Int32, "scala")     # "Int"

# Spark SQL types
get_target_type(UInt8, "spark")     # "ByteType"
get_target_type(Float32, "spark")   # "FloatType"

# Parquet physical types
get_target_type(UInt8, "parquet")   # "INT32" (promoted)
get_target_type(Float32, "parquet") # "FLOAT"
```

This currently supports [low-level Parquet
types](https://parquet.apache.org/docs/file-format/types/). We may consider [Parquet
logical types](https://github.com/apache/parquet-format/blob/master/LogicalTypes.md) in
the future.

### JSON Schema Generation

Abstract types integrate with JSON Schema generation:

```python
from overture.schema.core.json_schema import json_schema

schema = json_schema(Building)

# UInt8 generates proper integer constraints
assert schema["properties"]["num_floors"]["type"] == "integer"
assert schema["properties"]["num_floors"]["minimum"] == 0
assert schema["properties"]["num_floors"]["maximum"] == 255

# Float types get an explicit number type
assert schema["properties"]["height"]["type"] == "number"
```

### Type Registry

The system maintains a registry mapping concrete types to their abstract definitions:

```python
from overture.schema.core.types.abstract import (
    Float32,
    get_abstract_type
)

# Get the abstract type for a concrete type
abstract_type = get_abstract_type(UInt8)
abstract_type.get_target_type("scala")  # "Byte"
get_abstract_type(Float32).get_target_type("parquet")  # "FLOAT"
```

### Type Safety

The abstract data types provide strong type safety guarantees at both static and runtime levels:

**Static Type Checking**: mypy can distinguish between different abstract types, preventing common errors:

```python
from overture.schema.core.types.abstract import UInt8, UInt32

def process_floor_count(floors: UInt8) -> str:
    return f"Building has {floors} floors"

def process_area(area: UInt32) -> str:
    return f"Area: {area} sq meters"

# Type checker prevents mixing incompatible types
floors: UInt8 = 12
area: UInt32 = 2500

process_floor_count(area)   # mypy error: Expected UInt8, got UInt32
process_area(floors)        # mypy error: Expected UInt32, got UInt8
```

**Runtime Validation**: Pydantic automatically validates bounds and type constraints:

```python
# Automatic range validation
Building(num_floors=300)    # ValidationError: 300 exceeds UInt8 max (255)
Building(height=-10.5)      # ValidationError: negative height invalid
```

## Scoping System

The scoping system enables precise conditional application of rules based on geometric, temporal, directional, and subjective criteria. This is essential for transportation rules like speed limits, access restrictions, and other regulations that apply under specific conditions.

### Architecture

The scoping system follows a **mix-in architecture** with two tiers:

1. **Geometric Scoping**: Where along a linear feature (using linear referencing)
2. **Conditional Scoping**: When and how rules apply (temporal, directional, subjective)

### Core Scopes

#### Individual Scopes

Each scope class handles a specific dimension of conditional logic:

- **`GeometricRangeScope`**: Linear referencing with `between: [start, end]`
- **`TemporalScope`**: Time-based conditions using OSM opening hours format
- **`HeadingScope`**: Directional application (`forward`/`backward`)
- **`TravelModeScope`**: Travel mode filtering (car, bike, foot, etc.)
- **`PurposeOfUseScope`**: Usage purpose filtering (delivery, destination, etc.)
- **`RecognizedStatusScope`**: Recognition status (private, employee, etc.)
- **`VehicleScope`**: Vehicle attribute constraints (weight, height, etc.)

#### Composite Scoping

**`ScopingConditions`**: Inherits from all individual scopes to provide comprehensive scoping capabilities in a single class.

### Usage Patterns

#### Basic Geometric Scoping

```python
from overture.schema.core.common import GeometricRangeScope

class WidthRule(GeometricRangeScope):
    width: Dimension
```

#### Complex Conditional Scoping

```python
from overture.schema.core.common import GeometricRangeScope, ScopingConditions

class SpeedLimitWhenClause(
    TemporalScope,
    HeadingScope,
    PurposeOfUseScope,
    RecognizedStatusScope,
    TravelModeScope,
    VehicleScope
):
    pass

class SpeedLimitRule(GeometricRangeScope):
    max_speed: Speed
    when: Optional[SpeedLimitWhenClause] = None
```

#### Full Scoping Integration

```python
class AccessRestrictionRule(GeometricRangeScope):
    access_type: AccessType
    when: Optional[AccessRestrictionWhenClause] = None
```

### Examples

#### Temporal Speed Limit

```yaml
speed_limits:
  - between: [0, 1]
    max_speed: {value: 30, unit: km/h}
    when:
      during: "Mo-Fr 07:00-09:00,17:00-19:00"  # Rush hours only
```

#### Vehicle-Specific Access Restriction

```yaml
access_restrictions:
  - between: [0.2, 0.8]
    access_type: denied
    when:
      vehicle:
        - dimension: weight
          comparison: greater_than
          value: 7.5
          unit: t
```

#### Multi-Dimensional Scoping

```yaml
access_restrictions:
  - between: [0, 1]
    access_type: denied
    when:
      mode: [bus]
      during: "Mo-Fr 15:00-18:00"
      heading: forward
      using: [to_deliver]
```

### Design Principles

1. **Composability**: Mix-in design allows combining only needed scoping dimensions
2. **Reusability**: Base scope classes work across all rule types and themes
3. **Extensibility**: Easy to add new scoping dimensions or modify existing ones
4. **Type Safety**: Full Pydantic validation for all scoping conditions
5. **Linear Reference Integration**: Seamless integration with geometric positioning

### Rule Complexity Patterns

- **Simple Rules** (flags, dimensions): Geometric scoping only
- **Complex Rules** (speed limits, access): Geometric + conditional scoping
- **Transition Rules**: Full scoping including directional constraints

This scoping system provides the foundation for precise, flexible rule specification across all Overture Maps transportation features.
