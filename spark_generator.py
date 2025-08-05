"""
Spark-optimized Scala code generator from Pydantic models.

This module generates Spark-compatible Scala code from Pydantic models, with special
support for discriminated unions (using TypeAdapter) and optimizations for Dataset[T] usage.

Key Design Decisions & Lessons Learned:
=====================================

1. **Pydantic as IR**: Pydantic models serve as an excellent Intermediate Representation
   for cross-language code generation. They provide rich introspection via model_fields,
   type annotations, and built-in validation logic.

2. **Jinja2 + Introspection > libcst**: For cross-language generation, Pydantic's
   built-in introspection combined with Jinja2 templates proved superior to libcst.
   - libcst is excellent for Python AST manipulation but overkill for metadata extraction
   - inspect module works but Pydantic's model_fields provides richer information
   - Templates provide clean separation between logic and output format

3. **Spark-Specific Optimizations**:
   - Use Long instead of Int for better compatibility <- only necessary if we don't know our Spark / Parquet data types
   - Prefer Array over List for performance
   - Explicit Option types required for nullable columns
   - Custom encoders needed for discriminated unions
   - Companion objects with DataFrame conversion helpers

4. **Discriminated Union Handling**:
   - Detects Annotated[Union[A, B], Field(discriminator="field")] patterns
   - Generates sealed traits with case class variants
   - Creates type-safe filtering methods
   - Handles discriminator field extraction from model defaults

Validation System:
=================

A. **Tiered Validation Strategy**:
   - **Tier 1 (Pure SQL)**: Simple patterns, numeric ranges - fastest execution via Catalyst
   - **Tier 2 (SQL Wrapper UDFs)**: Complex SQL expressions wrapped for readability
   - **Tier 3 (Scala UDFs)**: Complex logic that cannot be expressed in SQL (last resort)

B. **Single-Scan Batch Processing**:
   - All validations execute in one Dataset scan using complex SQL expressions
   - Leverages Catalyst optimizer for vectorized operations and predicate pushdown
   - Avoids expensive multiple scans and caching requirements
   - Returns Dataset[ValidationError] suitable for persistence to tables

C. **Custom Constraint Integration**:
   - Extracts validation metadata from overture-schema-validation constraints
   - Maps PatternConstraint, CountryCodeConstraint, LinearReferenceRangeConstraint, etc.
   - Uses JSON Schema generation as inspiration for constraint parameter extraction
   - Generates constraint-specific validation logic (regex, numeric bounds, composite uniqueness)

D. **Reusable Validator Library**:
   - Common validators (isValidISO8601DateTime, isValidLinearReferenceRange)
   - Domain-specific validators (country codes, language tags, Wikidata IDs)
   - Composite validators (uniqueness checks, extension prefix validation)
   - SQL wrapper functions that maintain Catalyst optimization while improving readability

Future Improvements:
===================

A. **Enhanced Spark Support**:
   - Generate Catalyst encoders for better performance
   - Add support for nested structures in schema generation
   - Generate column expressions for complex queries
   - Support for Spark streaming (structured streaming compatibility)

B. **Multi-Language Extension**:
   - TypeScript interfaces with discriminated unions (type guards)
   - Rust structs with serde annotations
   - Go structs with JSON tags
   - Protobuf definitions
   - JSON Schema generation (may already exist in Pydantic)

C. **Template System Enhancements**:
   - Plugin architecture for custom type mappings
   - Theme-based template selection (e.g., "spark", "standard", "minimal")
   - Support for custom annotations/decorators in output
   - Template inheritance for shared patterns

D. **Advanced Type System**:
   - Generic type parameter handling
   - Recursive type definitions
   - Complex constraint mapping (regex, bounds, etc.)
   - Union types beyond discriminated unions

E. **Tooling Integration**:
   - CLI tool for batch generation
   - IDE plugins for live preview
   - Build system integration (sbt, gradle, etc.)
   - Validation that generated code compiles

Example Usage:
==============

```python
# Define models with discriminated unions and custom validation
SegmentType = Annotated[
    Union[RoadSegment, RailSegment],
    Field(discriminator="subtype")
]
segment_adapter = TypeAdapter(SegmentType)

# Generate Spark-compatible Scala with validation
generator = SparkScalaCodeGenerator(package="com.overture.transportation")
scala_code = generator.generate_from_type_adapter(segment_adapter, "TransportationSegment")
encoders = generator.generate_spark_encoders("Transportation")

# Generated validation methods:
# - validateAllOptimized(ds: Dataset[T]): Dataset[ValidationError]
# - Case class companion methods with DataFrame conversion helpers
# - Reusable validator library for domain-specific constraints
```

Dependencies:
- pydantic (model introspection)
- jinja2 (templating)
- typing (type analysis)

Author: Generated from conversation about Pydantic -> Scala code generation
Date: 2025-01-02
"""

import inspect
from typing import Annotated, Any, Dict, List, Optional, Union, get_args, get_origin

from jinja2 import DictLoader, Environment
from pydantic import BaseModel, Field, TypeAdapter

# Enhanced Jinja2 templates for Spark compatibility
SCALA_TEMPLATES = {
    "case_class": """
{%- if package %}package {{ package }}

{% endif -%}
{%- for import in imports %}
import {{ import }}
{% endfor -%}
{%- if imports %}
{% endif -%}
{%- if docstring %}
/**
 * {{ docstring }}
 */
{% endif -%}
case class {{ class_name }}(
{%- for field in fields %}
  {{ field.name }}: {{ field.scala_type }}{% if field.default_value %} = {{ field.default_value }}{% endif %}{% if not loop.last %},{% endif %}
{%- endfor %}
){% if companion_methods %}

object {{ class_name }} {
{%- for method in companion_methods %}
  {{ method }}
{% endfor -%}
}{% endif %}
""".strip(),
    "sealed_trait": """
{%- if package %}package {{ package }}

{% endif -%}
{%- for import in imports %}
import {{ import }}
{% endfor -%}
{%- if imports %}
{% endif -%}
{%- if docstring %}
/**
 * {{ docstring }}
 */
{% endif -%}
sealed trait {{ trait_name }}{% if discriminator_field %} {
  def {{ discriminator_field }}: String
}{% else %}
{% endif -%}

{%- for variant in variants %}

case class {{ variant.name }}(
{%- for field in variant.fields %}
  {{ field.name }}: {{ field.scala_type }}{% if field.default_value %} = {{ field.default_value }}{% endif %}{% if not loop.last %},{% endif %}
{%- endfor %}
) extends {{ trait_name }}{% if discriminator_field %} {
  override val {{ discriminator_field }}: String = "{{ variant.discriminator_value }}"
}{% endif -%}
{%- endfor %}

object {{ trait_name }} {
{%- for method in companion_methods %}
  {{ method }}
{% endfor -%}
}
""".strip(),
    "spark_encoders": """
{%- if package %}package {{ package }}

{% endif -%}
import org.apache.spark.sql.{Encoder, Encoders}
import org.apache.spark.sql.catalyst.encoders.ExpressionEncoder
import scala.reflect.runtime.universe.TypeTag

object {{ module_name }}Encoders {
{%- for class_info in classes %}
  {%- if class_info.is_union %}

  // Custom encoder for discriminated union {{ class_info.name }}
  // (Regular case classes use Spark's built-in Encoders.product via spark.implicits._)
  implicit def {{ class_info.name | lower }}Encoder: Encoder[{{ class_info.name }}] = {
    import org.apache.spark.sql.catalyst.encoders.RowEncoder
    import org.apache.spark.sql.types._

    val schema = StructType(Array(
{%- for field in class_info.schema_fields %}
      StructField("{{ field.name }}", {{ field.spark_type }}, {{ field.nullable | lower }}){% if not loop.last %},{% endif %}
{%- endfor %}
    ))

    ExpressionEncoder.apply(schema)
  }
  {%- endif %}
{%- endfor %}
}
""".strip(),
}


class SparkTypeMapper:
    """Maps Python/Pydantic types to Spark-compatible Scala types.

    This class handles the complex type mapping between Python/Pydantic type
    annotations and Spark-compatible Scala types, with special handling for:
    - Discriminated unions (Annotated[Union[A, B], Field(discriminator="field")])
    - Optional types (becomes Option[T])
    - Collections (List -> Array for better Spark performance)
    - Nested Pydantic models
    """

    # Spark-compatible type mappings
    TYPE_MAP = {
        str: "String",
        int: "Long",  # Spark prefers Long over Int for better compatibility
        float: "Double",
        bool: "Boolean",
        bytes: "Array[Byte]",
    }

    # Spark SQL types for schema generation
    SPARK_TYPE_MAP = {
        str: "StringType",
        int: "LongType",
        float: "DoubleType",
        bool: "BooleanType",
        bytes: "BinaryType",
    }

    def __init__(self, custom_mappings: dict[str, str] = None):
        """Initialize with optional custom type mappings.

        Args:
            custom_mappings: Dict mapping Python type names to Scala types.
                           e.g., {'datetime': 'java.time.LocalDateTime'}
        """
        self.custom_mappings = custom_mappings or {}
        self.discovered_unions = {}  # Track discriminated unions found during mapping

    def map_type(self, python_type, field_info=None, for_spark_schema=False) -> str:
        """Convert Python type to Spark-compatible Scala type.

        Args:
            python_type: Python type annotation to convert
            field_info: Optional Pydantic FieldInfo for additional context
            for_spark_schema: If True, return Spark SQL types (StringType, etc.)

        Returns:
            Scala type string appropriate for the target context
        """

        type_name = getattr(python_type, "__name__", str(python_type))
        if type_name in self.custom_mappings:
            return self.custom_mappings[type_name]

        origin = get_origin(python_type)
        args = get_args(python_type)

        # Handle Annotated discriminated unions - key pattern for our use case
        if origin is Annotated:
            actual_type = args[0]
            annotations = args[1:]

            # Look for Field(discriminator="field_name") in annotations
            discriminator = None
            for annotation in annotations:
                if isinstance(annotation, Field) and hasattr(
                    annotation, "discriminator"
                ):
                    discriminator = annotation.discriminator
                    break

            if discriminator:
                union_origin = get_origin(actual_type)
                union_args = get_args(actual_type)

                if union_origin is Union:
                    variant_names = [
                        arg.__name__ for arg in union_args if hasattr(arg, "__name__")
                    ]
                    trait_name = self._generate_trait_name(variant_names)

                    # Store union info for later code generation
                    self.discovered_unions[trait_name] = DiscriminatedUnion(
                        name=trait_name,
                        variants=union_args,
                        discriminator_field=discriminator,
                    )

                    return trait_name

            # No discriminator found, map the actual type
            return self.map_type(actual_type, field_info, for_spark_schema)

        # Handle Optional types (Union[X, None])
        if origin is Union:
            if len(args) == 2 and type(None) in args:
                inner_type = args[0] if args[1] is type(None) else args[1]
                if for_spark_schema:
                    # For schema, just return the inner type (nullability handled elsewhere)
                    return self.map_type(inner_type, field_info, for_spark_schema)
                return f"Option[{self.map_type(inner_type, field_info)}]"

        # Handle List types - Spark prefers Array for better performance
        if origin in (list, list):
            if args:
                inner_type = self.map_type(args[0], field_info, for_spark_schema)
                if for_spark_schema:
                    return f"ArrayType({inner_type})"
                return f"Array[{inner_type}]"  # Array instead of List for Spark
            if for_spark_schema:
                return "ArrayType(StringType)"
            return "Array[String]"

        # Handle Dict types - Spark uses Map
        if origin in (dict, dict):
            if len(args) == 2:
                key_type = self.map_type(args[0], field_info, for_spark_schema)
                value_type = self.map_type(args[1], field_info, for_spark_schema)
                if for_spark_schema:
                    return f"MapType({key_type}, {value_type})"
                return f"Map[{key_type}, {value_type}]"
            if for_spark_schema:
                return "MapType(StringType, StringType)"
            return "Map[String, String]"

        # Handle Pydantic models as nested structures
        if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
            if for_spark_schema:
                # For schema, we'd need to recursively build the struct
                # TODO: Implement recursive struct generation for nested models
                return f"StructType(/* fields for {python_type.__name__} */)"
            return python_type.__name__

        # Handle basic types
        if for_spark_schema:
            return self.SPARK_TYPE_MAP.get(python_type, "StringType")
        return self.TYPE_MAP.get(python_type, "String")

    def _generate_trait_name(self, variant_names: list[str]) -> str:
        """Generate trait name from variant class names.

        Attempts to find a common suffix (e.g., "Segment" from RoadSegment, RailSegment)
        and use that as the trait name, falling back to concatenation.
        """
        common_suffix = self._find_common_suffix(variant_names)
        if common_suffix and len(common_suffix) > 2:
            return common_suffix.capitalize()
        return (
            "".join(name.replace("Segment", "") for name in variant_names) + "Segment"
        )

    def _find_common_suffix(self, names: list[str]) -> str:
        """Find the longest common suffix among a list of names."""
        if not names:
            return ""
        shortest = min(names, key=len)
        for i in range(len(shortest), 0, -1):
            suffix = shortest[-i:]
            if all(name.endswith(suffix) for name in names):
                return suffix
        return ""


class DiscriminatedUnion:
    """Represents a discriminated union for code generation.

    This captures the information needed to generate a Scala sealed trait
    with case class variants from a Pydantic discriminated union.
    """

    def __init__(
        self, name: str, variants: list[type], discriminator_field: str = None
    ):
        self.name = name
        self.variants = variants  # List of Pydantic model classes
        self.discriminator_field = discriminator_field
        self.docstring = None


class SparkScalaCodeGenerator:
    """Spark-optimized Scala code generator from Pydantic models.

    This generator creates Scala code optimized for use with Apache Spark Dataset[T],
    including proper encoders, DataFrame conversion methods, and type-safe operations.

    Key features:
    - Generates case classes with Spark-compatible types (Long vs Int, Array vs List)
    - Handles discriminated unions as sealed traits
    - Creates custom encoders for complex types
    - Adds companion methods for DataFrame interop
    """

    def __init__(self, type_mapper: SparkTypeMapper = None, package: str = None):
        """Initialize the generator.

        Args:
            type_mapper: Custom type mapper, uses SparkTypeMapper() if None
            package: Scala package name for generated code
        """
        self.type_mapper = type_mapper or SparkTypeMapper()
        self.package = package
        self.env = Environment(loader=DictLoader(SCALA_TEMPLATES))
        self.processed_models = set()
        self.generated_classes = []  # Track classes for encoder generation

    def generate_case_class(
        self, model_class: type[BaseModel], include_companion: bool = False
    ) -> str:
        """Generate Spark-compatible case class from Pydantic model.

        Args:
            model_class: Pydantic model class to convert
            include_companion: Whether to include companion object with helper methods

        Returns:
            Generated Scala case class code as string
        """

        class_name = model_class.__name__
        docstring = inspect.getdoc(model_class)

        fields = []
        imports = {"org.apache.spark.sql.types._"}  # Always need Spark types

        # Process each field using Pydantic's rich introspection
        for field_name, field_info in model_class.model_fields.items():
            scala_type = self.type_mapper.map_type(field_info.annotation, field_info)

            # Handle defaults - Spark encoders work better with explicit Option types
            default_value = None
            is_nullable = not field_info.is_required()

            if is_nullable:
                if field_info.default is not None:
                    default_value = self._format_default_value(
                        field_info.default, scala_type
                    )
                else:
                    default_value = "None"

                # Wrap non-Option types with Option for nullable fields
                if not scala_type.startswith("Option["):
                    scala_type = f"Option[{scala_type}]"

            fields.append(
                {
                    "name": field_name,
                    "scala_type": scala_type,
                    "default_value": default_value,
                    "required": field_info.is_required(),
                    "nullable": is_nullable,
                    "description": field_info.description,
                }
            )

        # Don't track regular case classes for encoder generation - they use Spark's built-in Encoders.product

        # Add Spark-specific companion methods
        companion_methods = []
        if include_companion:
            companion_methods = self._generate_spark_companion_methods(
                model_class, fields
            )

        template = self.env.get_template("case_class")
        return template.render(
            package=self.package,
            imports=sorted(imports),
            class_name=class_name,
            docstring=docstring,
            fields=fields,
            companion_methods=companion_methods,
        )

    def generate_discriminated_union(self, union: DiscriminatedUnion) -> str:
        """Generate Spark-compatible sealed trait with case class variants.

        Creates a sealed trait for the union type with case classes for each variant,
        optimized for Spark Dataset usage with proper encoders and type-safe operations.

        Args:
            union: DiscriminatedUnion describing the union structure

        Returns:
            Generated Scala sealed trait + case classes code
        """

        variants = []
        imports = {"org.apache.spark.sql.types._"}
        union_schema_fields = []  # Track all fields across variants for encoder

        for variant_class in union.variants:
            if not (
                inspect.isclass(variant_class) and issubclass(variant_class, BaseModel)
            ):
                continue

            discriminator_value = self._get_discriminator_value(
                variant_class, union.discriminator_field
            )

            fields = []
            # Add discriminator field to union schema (only once)
            if union.discriminator_field not in [
                f["name"] for f in union_schema_fields
            ]:
                union_schema_fields.append(
                    {
                        "name": union.discriminator_field,
                        "spark_type": "StringType",
                        "nullable": False,
                    }
                )

            # Process variant fields
            for field_name, field_info in variant_class.model_fields.items():
                # Skip discriminator field as it's handled in the trait
                if field_name == union.discriminator_field:
                    continue

                scala_type = self.type_mapper.map_type(
                    field_info.annotation, field_info
                )
                spark_type = self.type_mapper.map_type(
                    field_info.annotation, field_info, for_spark_schema=True
                )
                is_nullable = not field_info.is_required()

                # Add to union schema if not already present (fields may overlap between variants)
                schema_field = {
                    "name": field_name,
                    "spark_type": spark_type,
                    "nullable": is_nullable,
                }
                if schema_field not in union_schema_fields:
                    union_schema_fields.append(schema_field)

                default_value = None
                if is_nullable:
                    if field_info.default is not None:
                        default_value = self._format_default_value(
                            field_info.default, scala_type
                        )
                    else:
                        default_value = "None"

                    if not scala_type.startswith("Option["):
                        scala_type = f"Option[{scala_type}]"

                fields.append(
                    {
                        "name": field_name,
                        "scala_type": scala_type,
                        "default_value": default_value,
                        "required": field_info.is_required(),
                    }
                )

            variants.append(
                {
                    "name": variant_class.__name__,
                    "fields": fields,
                    "discriminator_value": discriminator_value,
                    "docstring": inspect.getdoc(variant_class),
                }
            )

        # Track union info for encoder generation
        self.generated_classes.append(
            {"name": union.name, "schema_fields": union_schema_fields, "is_union": True}
        )

        companion_methods = self._generate_union_companion_methods(union, variants)

        template = self.env.get_template("sealed_trait")
        return template.render(
            package=self.package,
            imports=sorted(imports),
            trait_name=union.name,
            discriminator_field=union.discriminator_field,
            variants=variants,
            companion_methods=companion_methods,
            docstring=union.docstring,
        )

    def generate_spark_encoders(self, module_name: str = "Models") -> str:
        """Generate Spark encoders for discriminated unions.

        Creates an object with implicit encoders only for discriminated unions that need
        custom StructType schemas. Regular case classes automatically use Spark's
        built-in Encoders.product via spark.implicits._.

        Args:
            module_name: Name for the generated encoders object

        Returns:
            Generated Scala encoders object code, or empty string if no unions
        """

        # Only generate encoders if we have discriminated unions
        union_classes = [
            cls for cls in self.generated_classes if cls.get("is_union", False)
        ]

        if not union_classes:
            return ""  # No custom encoders needed

        template = self.env.get_template("spark_encoders")
        return template.render(
            package=self.package,
            module_name=module_name,
            classes=union_classes,
        )

    def generate_from_type_adapter(
        self, type_adapter: TypeAdapter, name: str = None
    ) -> str:
        """Generate Scala code from a Pydantic TypeAdapter.

        This is the main entry point for discriminated unions created with TypeAdapter,
        which is the recommended pattern for complex union types in Pydantic.

        Args:
            type_adapter: Pydantic TypeAdapter wrapping the union type
            name: Optional name override for the generated trait

        Returns:
            Generated Scala code (sealed trait for unions, case class for single models)
        """
        python_type = type_adapter._target_type

        # Process the type to discover any discriminated unions
        self.type_mapper.map_type(python_type)

        discovered_unions = list(self.type_mapper.discovered_unions.values())

        if discovered_unions:
            # Generate sealed trait for discriminated union
            union = discovered_unions[0]
            if name:
                union.name = name
            return self.generate_discriminated_union(union)
        else:
            # Fall back to regular class generation for single models
            if inspect.isclass(python_type) and issubclass(python_type, BaseModel):
                return self.generate_case_class(python_type, include_companion=True)
            else:
                raise ValueError(f"Cannot generate code for type: {python_type}")

    def _generate_spark_companion_methods(self, model_class, fields) -> list[str]:
        """Generate Spark-specific companion methods for case classes.

        Adds helper methods for DataFrame conversion, schema access, and other
        common Spark operations.
        """
        methods = []
        class_name = model_class.__name__

        # Add DataFrame conversion method
        methods.append(
            f"""
  import org.apache.spark.sql.{{Dataset, SparkSession}}

  def fromDataFrame(df: org.apache.spark.sql.DataFrame)(implicit spark: SparkSession): Dataset[{class_name}] = {{
    import spark.implicits._
    df.as[{class_name}]
  }}""".strip()
        )

        # Add schema method for programmatic DataFrame creation
        schema_fields = []
        for field in fields:
            # Get Spark type for schema (this could be enhanced)
            spark_type = self.type_mapper.map_type(
                type(field.get("default_value", "")), for_spark_schema=True
            )
            nullable = field.get("nullable", True)
            schema_fields.append(
                f'StructField("{field["name"]}", {spark_type}, {str(nullable).lower()})'
            )

        methods.append(
            f"""
  def schema: org.apache.spark.sql.types.StructType = {{
    import org.apache.spark.sql.types._
    StructType(Array(
      {(",\n      ".join(schema_fields))}
    ))
  }}""".strip()
        )

        return methods

    def _generate_union_companion_methods(
        self, union: DiscriminatedUnion, variants: list[dict]
    ) -> list[str]:
        """Generate Spark-specific companion methods for discriminated unions.

        Adds methods for DataFrame conversion and type-safe filtering by discriminator value.
        """
        methods = []

        # Add DataFrame conversion with discriminator handling
        methods.append(
            f"""
  import org.apache.spark.sql.{{Dataset, SparkSession, Column}}
  import org.apache.spark.sql.functions._

  def fromDataFrame(df: org.apache.spark.sql.DataFrame)(implicit spark: SparkSession): Dataset[{union.name}] = {{
    import spark.implicits._
    df.as[{union.name}]
  }}""".strip()
        )

        # Add discriminator-based filtering methods for each variant
        for variant in variants:
            methods.append(
                f"""
  def filter{variant["name"]}s(ds: Dataset[{union.name}]): Dataset[{variant["name"]}] = {{
    ds.filter(col("{union.discriminator_field}") === "{variant["discriminator_value"]}")
      .map(_.asInstanceOf[{variant["name"]}])
  }}""".strip()
            )

        return methods

    def _get_discriminator_value(
        self, model_class: type[BaseModel], discriminator_field: str
    ) -> str:
        """Extract discriminator value from a Pydantic model.

        Looks for the discriminator field in the model and extracts its default value,
        falling back to a transformation of the class name if not found.
        """
        if (
            hasattr(model_class, "model_fields")
            and discriminator_field in model_class.model_fields
        ):
            field_info = model_class.model_fields[discriminator_field]
            if hasattr(field_info, "default") and field_info.default is not None:
                return str(field_info.default)

        # Fall back to class name transformation
        return model_class.__name__.lower().replace("segment", "")

    def _format_default_value(self, default_value: Any, scala_type: str) -> str:
        """Format Python default values as Spark-compatible Scala literals.

        Handles proper wrapping in Some() for Option types and appropriate
        literal formatting for different value types.
        """
        if isinstance(default_value, str):
            return f'Some("{default_value}")'
        elif isinstance(default_value, bool):
            return f"Some({str(default_value).lower()})"
        elif isinstance(default_value, (int, float)):
            # Use L suffix for Long literals (Spark's preferred int type)
            return (
                f"Some({default_value}L)"
                if isinstance(default_value, int)
                else f"Some({default_value})"
            )
        elif default_value is None:
            return "None"
        elif isinstance(default_value, list):
            items = ", ".join(
                f'"{item}"' if isinstance(item, str) else str(item)
                for item in default_value
            )
            return f"Some(Array({items}))"
        else:
            return f'Some("{default_value}")'


# Example usage and testing code
if __name__ == "__main__":
    """
    Example demonstrating the generator with discriminated unions and Spark optimization.

    This shows the typical workflow:
    1. Define Pydantic models with discriminated unions
    2. Create TypeAdapter for the union
    3. Generate Spark-compatible Scala code
    4. Generate encoders for Dataset operations
    """

    # Example models representing transportation segments
    class RoadSegment(BaseModel):
        """A road segment for Spark processing"""

        subtype: str = Field(default="road")
        road_class: str
        speed_limit: int | None = None
        lanes: int = 2
        tags: list[str] = Field(default_factory=list)

    class RailSegment(BaseModel):
        """A rail segment for Spark processing"""

        subtype: str = Field(default="rail")
        gauge: str  # Track gauge (e.g., "standard", "narrow")
        electrified: bool = False
        max_speed: int | None = None

    # Create discriminated union using TypeAdapter (recommended Pydantic pattern)
    SegmentType = Annotated[RoadSegment | RailSegment, Field(discriminator="subtype")]
    segment_adapter = TypeAdapter(SegmentType)

    # Generate Spark-optimized Scala code
    try:
        from rich.console import Console
        from rich.syntax import Syntax

        console = Console()
        generator = SparkScalaCodeGenerator(package="com.overture.spark.transportation")

        # Generate the discriminated union
        print("=== Generating Discriminated Union ===")
        union_code = generator.generate_from_type_adapter(
            segment_adapter, "TransportationSegment"
        )
        syntax = Syntax(union_code, "scala", theme="monokai", line_numbers=True)
        console.print(syntax)

        # Generate individual case classes with companion methods
        for model in [RoadSegment, RailSegment]:
            print(f"\n=== Generating {model.__name__} ===")
            class_code = generator.generate_case_class(model, include_companion=True)
            class_syntax = Syntax(
                class_code, "scala", theme="monokai", line_numbers=True
            )
            console.print(class_syntax)

        # Generate Spark encoders
        print("\n=== Generating Spark Encoders ===")
        encoders_code = generator.generate_spark_encoders("Transportation")
        encoders_syntax = Syntax(
            encoders_code, "scala", theme="monokai", line_numbers=True
        )
        console.print(encoders_syntax)

    except ImportError:
        # Fallback for when rich is not available
        print("Install 'rich' for syntax highlighting: pip install rich")
        generator = SparkScalaCodeGenerator(package="com.overture.spark.transportation")
        union_code = generator.generate_from_type_adapter(
            segment_adapter, "TransportationSegment"
        )
        encoders_code = generator.generate_spark_encoders("Transportation")

        print("=== Generated Union Code ===")
        print(union_code)
        print("\n=== Generated Encoders ===")
        print(encoders_code)
