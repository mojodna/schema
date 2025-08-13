"""Spark SQL validation expression generator.

This module generates Spark-compatible Scala validation code that implements the
tiered validation strategy described in spark_generator.py.
"""

from typing import Any, Dict, List, Optional, Union

from jinja2 import DictLoader, Environment

from .validation import SparkValidationExtractor, ValidationConstraint

# Jinja2 templates for Spark validation code generation
SPARK_VALIDATION_TEMPLATES = {
    "validation_error_case_class": """
case class ValidationError(
  recordId: String,
  fieldName: String,
  constraintType: String,
  errorMessage: String,
  fieldValue: Option[String] = None
)

""".strip(),
    "companion_validation_methods": """

  // Additional imports for validation
  import org.apache.spark.sql.functions._
  import org.apache.spark.sql.Column

  // === Validation Methods ===

  /**
   * Validate all constraints and return Dataset[ValidationError].
   *
   * @param ds Dataset to validate
   * @param idColumn Column name containing unique record identifiers
   * @return Dataset of validation errors
   */
  def validateAll(ds: Dataset[{{ model_name }}], idColumn: String = "id"): Dataset[ValidationError] = {
    import ds.sparkSession.implicits._

    // Generate validation expressions for each constraint
    val validationColumns = List(
{%- for validation_expr in validation_expressions %}
      {{ validation_expr }}{% if not loop.last %},{% endif %}
{%- endfor %}
    )

    // Combine all validation results and explode into individual error records
    ds.select(
      col(idColumn).as("recordId"),
      array(validationColumns: _*).as("errors")
    )
    .select(
      col("recordId"),
      explode(col("errors")).as("error")
    )
    .filter(col("error").isNotNull)
    .select(
      col("recordId"),
      col("error.fieldName"),
      col("error.constraintType"),
      col("error.errorMessage"),
      col("error.fieldValue")
    )
    .as[ValidationError]
  }

  /**
   * Count validation errors by constraint type.
   */
  def getValidationSummary(ds: Dataset[{{ model_name }}], idColumn: String = "id"): Dataset[(String, Long)] = {
    validateAll(ds, idColumn)
      .groupBy("constraintType")
      .count()
      .as[(String, Long)]
  }

  // === Private Validation Helper Methods ===

{%- for validator in tier1_validators %}
  {{ validator | replace("def validate", "private def validate") }}
{% endfor %}

{%- for validator in tier2_validators %}
  {{ validator | replace("def validate", "private def validate") }}
{% endfor %}

{%- for validator in tier3_validators %}
  {{ validator | replace("def validate", "private def validate") }}
{% endfor %}
""".strip(),
    "batch_validator": """
package {{ package }}

import org.apache.spark.sql.{Column, Dataset, SparkSession}
import org.apache.spark.sql.functions._
import org.apache.spark.sql.types._
import {{ package }}.{{ model_name }}Validators._

case class ValidationError(
  recordId: String,
  fieldName: String,
  constraintType: String,
  errorMessage: String,
  fieldValue: Option[String] = None
)

/**
 * Single-scan batch validation for {{ model_name }}.
 *
 * Validates all constraints in one Dataset scan using complex SQL expressions
 * leveraging Catalyst optimizer for vectorized operations and predicate pushdown.
 */
object {{ model_name }}BatchValidator {

  /**
   * Validate all constraints and return Dataset[ValidationError].
   *
   * @param ds Dataset to validate
   * @param idColumn Column name containing unique record identifiers
   * @return Dataset of validation errors
   */
  def validateAllOptimized(ds: Dataset[{{ model_name }}], idColumn: String = "id"): Dataset[ValidationError] = {
    import ds.sparkSession.implicits._

    // Generate validation expressions for each constraint
    val validationColumns = List(
{%- for validation_expr in validation_expressions %}
      {{ validation_expr }}{% if not loop.last %},{% endif %}
{%- endfor %}
    )

    // Combine all validation results and explode into individual error records
    ds.select(
      col(idColumn).as("recordId"),
      array(validationColumns: _*).as("errors")
    )
    .select(
      col("recordId"),
      explode(col("errors")).as("error")
    )
    .filter(col("error").isNotNull)
    .select(
      col("recordId"),
      col("error.fieldName"),
      col("error.constraintType"),
      col("error.errorMessage"),
      col("error.fieldValue")
    )
    .as[ValidationError]
  }

  /**
   * Count validation errors by constraint type.
   */
  def getValidationSummary(ds: Dataset[{{ model_name }}], idColumn: String = "id"): Dataset[(String, Long)] = {
    validateAllOptimized(ds, idColumn)
      .groupBy("constraintType")
      .count()
      .as[(String, Long)]
  }
}
""".strip(),
}


class SparkValidationCodeGenerator:
    """Generates Spark validation code from extracted constraints."""

    def __init__(self, package: str | None = None):
        self.package = package or "com.overture.validation"
        self.env = Environment(loader=DictLoader(SPARK_VALIDATION_TEMPLATES))
        self.extractor = SparkValidationExtractor()

    def _escape_regex_for_scala(self, pattern: str) -> str:
        """Escape a regex pattern for use in Scala string literals."""
        # Escape backslashes for Scala string literals
        return pattern.replace("\\", "\\\\")

    def _get_length_function(
        self, field_name: str, constraint: ValidationConstraint
    ) -> str:
        """Get appropriate length function based on field type."""
        # Use the stored field type if available
        if hasattr(constraint, "field_python_type") and constraint.field_python_type:
            field_type = constraint.field_python_type

            # Check if it's a list/array type
            if self._is_array_type(field_type):
                return "size"  # For arrays: size(column)

        # Fall back to heuristics for field name
        if field_name.endswith("_levels"):
            return "size"  # address_levels is definitely an array

        return "length"  # For strings: length(column)

    def _is_array_type(self, type_annotation: Any) -> bool:
        """Check if a type annotation represents an array/list type."""
        from typing import get_args, get_origin

        # Handle Union types (like Optional[list[...]])
        origin = get_origin(type_annotation)
        if origin is Union:
            args = get_args(type_annotation)
            for arg in args:
                if arg is not type(None) and self._is_array_type(arg):
                    return True
            return False

        # Check for list types
        if origin is list or (hasattr(list, "__origin__") and origin is list):
            return True

        # Handle types.UnionType (new union syntax like list[T] | None)
        if hasattr(type_annotation, "__origin__"):
            origin = getattr(type_annotation, "__origin__", None)
            if origin is list:
                return True

        # Check string representation for common array patterns
        type_str = str(type_annotation)
        return "list[" in type_str or "List[" in type_str or "Array[" in type_str

    def generate_validation_library(self, model_class, model_name: str = None) -> str:
        """Generate reusable validator library for a model."""
        if model_name is None:
            model_name = model_class.__name__

        constraints = self.extractor.extract_constraints_from_model(model_class)

        # Group constraints by tier
        tier1_validators = []
        tier2_validators = []
        tier3_validators = []

        for constraint in constraints:
            if constraint.tier == 1:
                validator_code = self._generate_tier1_validator(constraint)
                if validator_code:
                    tier1_validators.append(validator_code)
            elif constraint.tier == 2:
                validator_code = self._generate_tier2_validator(constraint)
                if validator_code:
                    tier2_validators.append(validator_code)
            elif constraint.tier == 3:
                validator_code = self._generate_tier3_validator(constraint)
                if validator_code:
                    tier3_validators.append(validator_code)

        template = self.env.get_template("validator_library")
        return template.render(
            package=self.package,
            model_name=model_name,
            tier1_validators=tier1_validators,
            tier2_validators=tier2_validators,
            tier3_validators=tier3_validators,
        )

    def generate_batch_validator(self, model_class, model_name: str = None) -> str:
        """Generate single-scan batch validator for a model."""
        if model_name is None:
            model_name = model_class.__name__

        constraints = self.extractor.extract_constraints_from_model(model_class)
        validation_expressions = []

        for constraint in constraints:
            expr = self._generate_validation_expression(constraint)
            if expr:
                validation_expressions.append(expr)

        template = self.env.get_template("batch_validator")
        return template.render(
            package=self.package,
            model_name=model_name,
            validation_expressions=validation_expressions,
        )

    def generate_companion_validation_methods(
        self, model_class, model_name: str = None
    ) -> str:
        """Generate validation methods for companion object integration."""
        if model_name is None:
            model_name = model_class.__name__

        constraints = self.extractor.extract_constraints_from_model(model_class)

        # Group constraints by tier
        tier1_validators = []
        tier2_validators = []
        tier3_validators = []
        validation_expressions = []

        for constraint in constraints:
            expr = self._generate_validation_expression(constraint)
            if expr:
                validation_expressions.append(expr)

            if constraint.tier == 1:
                validator_code = self._generate_tier1_validator(constraint)
                if validator_code:
                    tier1_validators.append(validator_code)
            elif constraint.tier == 2:
                validator_code = self._generate_tier2_validator(constraint)
                if validator_code:
                    tier2_validators.append(validator_code)
            elif constraint.tier == 3:
                validator_code = self._generate_tier3_validator(constraint)
                if validator_code:
                    tier3_validators.append(validator_code)

        template = self.env.get_template("companion_validation_methods")
        return template.render(
            model_name=model_name,
            validation_expressions=validation_expressions,
            tier1_validators=tier1_validators,
            tier2_validators=tier2_validators,
            tier3_validators=tier3_validators,
        )

    def generate_validation_error_case_class(self) -> str:
        """Generate the top-level ValidationError case class."""
        template = self.env.get_template("validation_error_case_class")
        return template.render()

    def _generate_tier1_validator(self, constraint: ValidationConstraint) -> str | None:
        """Generate Tier 1 (Pure SQL) validator."""
        field_name = constraint.field_name
        constraint_type = constraint.constraint_type
        params = constraint.constraint_params

        if constraint_type == "pattern":
            pattern = params.get("pattern", "")
            escaped_pattern = self._escape_regex_for_scala(pattern)
            error_msg = params.get("error_message", f"Invalid {field_name} format")
            return f'''
  /**
   * Validate {field_name} matches pattern: {pattern}
   */
  def validate{field_name.title()}Pattern(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when(column.rlike("{escaped_pattern}"), lit(null))
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("pattern").as("constraintType"),
          lit("{error_msg}").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        elif constraint_type in [
            "country_code",
            "region_code",
            "language_tag",
            "iso8601_datetime",
            "category_pattern",
            "wikidata_id",
            "phone_number",
            "hex_color",
            "no_whitespace",
            "whitespace_trimmed",
        ]:
            pattern = params.get("pattern", "")
            escaped_pattern = self._escape_regex_for_scala(pattern)
            return f'''
  /**
   * Validate {field_name} {constraint_type} format
   */
  def validate{field_name.title()}{constraint_type.title().replace("_", "")}(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when(column.rlike("{escaped_pattern}"), lit(null))
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("{constraint_type}").as("constraintType"),
          lit("Invalid {constraint_type.replace("_", " ")} format").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        elif constraint_type == "numeric_range":
            min_val = params.get("min_value")
            max_val = params.get("max_value")
            return f'''
  /**
   * Validate {field_name} numeric range [{min_val}, {max_val}]
   */
  def validate{field_name.title()}Range(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when(column >= {min_val} && column <= {max_val}, lit(null))
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("numeric_range").as("constraintType"),
          lit("Value must be between {min_val} and {max_val}").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        elif constraint_type.startswith("string_"):
            constraint_name = constraint_type.replace("string_", "")
            constraint_value = params.get(constraint_name)

            if constraint_name == "min_length":
                length_func = self._get_length_function(field_name, constraint)
                return f'''
  /**
   * Validate {field_name} minimum length: {constraint_value}
   */
  def validate{field_name.title()}MinLength(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when({length_func}(column) >= {constraint_value}, lit(null))
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("min_length").as("constraintType"),
          lit("Minimum length is {constraint_value}").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

            elif constraint_name == "max_length":
                length_func = self._get_length_function(field_name, constraint)
                return f'''
  /**
   * Validate {field_name} maximum length: {constraint_value}
   */
  def validate{field_name.title()}MaxLength(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when({length_func}(column) <= {constraint_value}, lit(null))
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("max_length").as("constraintType"),
          lit("Maximum length is {constraint_value}").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        elif constraint_type.startswith("numeric_"):
            constraint_name = constraint_type.replace("numeric_", "")
            constraint_value = params.get(constraint_name)

            operators = {"ge": ">=", "le": "<=", "gt": ">", "lt": "<"}
            op_symbol = operators.get(constraint_name, "==")

            return f'''
  /**
   * Validate {field_name} {constraint_name}: {op_symbol} {constraint_value}
   */
  def validate{field_name.title()}{constraint_name.title()}(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when(column {op_symbol} {constraint_value}, lit(null))
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("{constraint_type}").as("constraintType"),
          lit("Value must be {op_symbol} {constraint_value}").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        return None

    def _generate_tier2_validator(self, constraint: ValidationConstraint) -> str | None:
        """Generate Tier 2 (SQL Wrapper UDF) validator."""
        field_name = constraint.field_name
        constraint_type = constraint.constraint_type
        params = constraint.constraint_params

        if constraint_type == "linear_reference_range":
            return f'''
  /**
   * Validate {field_name} linear reference range [start, end] where 0.0 <= start < end <= 1.0
   */
  def validate{field_name.title()}LinearReference(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when(
        size(column) === 2 &&
        column.getItem(0) >= 0.0 && column.getItem(0) <= 1.0 &&
        column.getItem(1) >= 0.0 && column.getItem(1) <= 1.0 &&
        column.getItem(0) < column.getItem(1),
        lit(null)
      )
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("linear_reference_range").as("constraintType"),
          lit("Linear reference range must be [start, end] where 0.0 <= start < end <= 1.0").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        elif constraint_type == "unique_items":
            return f'''
  /**
   * Validate {field_name} has unique items
   */
  def validate{field_name.title()}UniqueItems(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when(size(column) === size(array_distinct(column)), lit(null))
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("unique_items").as("constraintType"),
          lit("All items must be unique").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        elif constraint_type == "json_pointer":
            return f'''
  /**
   * Validate {field_name} is a valid JSON Pointer (RFC 6901)
   */
  def validate{field_name.title()}JsonPointer(column: Column): Column = {{
    when(column.isNull, lit(null))
      .when(
        column === "" || column.startsWith("/"),
        lit(null)
      )
      .otherwise(
        struct(
          lit("{field_name}").as("fieldName"),
          lit("json_pointer").as("constraintType"),
          lit("JSON Pointer must start with '/' or be empty string").as("errorMessage"),
          column.cast("string").as("fieldValue")
        )
      )
  }}'''.strip()

        return None

    def _generate_tier3_validator(self, constraint: ValidationConstraint) -> str | None:
        """Generate Tier 3 (Scala UDF) validator."""
        constraint_type = constraint.constraint_type
        params = constraint.constraint_params

        if constraint_type == "required_if":
            condition_field = params["condition_field"]
            condition_value = params["condition_value"]
            required_fields = params["required_fields"]
            required_fields_str = ", ".join(f'"{field}"' for field in required_fields)

            return f'''
  /**
   * Validate required_if: {required_fields} required when {condition_field} = {condition_value}
   */
  def validateRequiredIf(row: Row): Option[ValidationError] = {{
    val conditionValue = Option(row.getAs[Any]("{condition_field}"))
    val requiredFields = Array({required_fields_str})

    if (conditionValue.contains({repr(condition_value)})) {{
      val missingFields = requiredFields.filter(field =>
        row.fieldIndex(field) < 0 || row.getAs[Any](field) == null
      )

      if (missingFields.nonEmpty) {{
        Some(ValidationError(
          recordId = row.getAs[String]("id"),
          fieldName = "__model__",
          constraintType = "required_if",
          errorMessage = s"Fields ${{missingFields.mkString(", ")}} are required when {condition_field} = {condition_value}",
          fieldValue = None
        ))
      }} else None
    }} else None
  }}'''.strip()

        elif constraint_type == "exactly_one_of":
            field_names = params["field_names"]
            field_names_str = ", ".join(f'"{field}"' for field in field_names)

            return f"""
  /**
   * Validate exactly_one_of: exactly one of {field_names} must be true
   */
  def validateExactlyOneOf(row: Row): Option[ValidationError] = {{
    val fields = Array({field_names_str})
    val trueFields = fields.filter(field =>
      row.fieldIndex(field) >= 0 && row.getAs[Boolean](field) == true
    )

    if (trueFields.length != 1) {{
      Some(ValidationError(
        recordId = row.getAs[String]("id"),
        fieldName = "__model__",
        constraintType = "exactly_one_of",
        errorMessage = s"Exactly one of {field_names_str} must be true, but found ${{trueFields.length}}: ${{trueFields.mkString(", ")}}",
        fieldValue = None
      ))
    }} else None
  }}""".strip()

        # Add other Tier 3 validators as needed...

        return None

    def _generate_validation_expression(
        self, constraint: ValidationConstraint
    ) -> str | None:
        """Generate validation expression for batch validator."""
        field_name = constraint.field_name
        constraint_type = constraint.constraint_type

        if constraint.tier == 1:
            # Direct SQL validation
            if constraint_type == "pattern":
                return f'validate{field_name.title()}Pattern(col("{field_name}"))'
            elif constraint_type in [
                "country_code",
                "region_code",
                "language_tag",
                "iso8601_datetime",
                "category_pattern",
                "wikidata_id",
                "phone_number",
                "hex_color",
                "no_whitespace",
                "whitespace_trimmed",
            ]:
                method_name = constraint_type.title().replace("_", "")
                return f'validate{field_name.title()}{method_name}(col("{field_name}"))'
            elif constraint_type == "numeric_range":
                return f'validate{field_name.title()}Range(col("{field_name}"))'
            elif constraint_type.startswith("string_"):
                constraint_name = constraint_type.replace("string_", "")
                # Convert min_length -> MinLength (not Min_Length)
                method_name = "".join(
                    word.title() for word in constraint_name.split("_")
                )
                return f'validate{field_name.title()}{method_name}(col("{field_name}"))'
            elif constraint_type.startswith("numeric_"):
                constraint_name = constraint_type.replace("numeric_", "")
                # Convert constraint names like "ge" -> "Ge"
                method_name = constraint_name.title()
                return f'validate{field_name.title()}{method_name}(col("{field_name}"))'

        elif constraint.tier == 2:
            # SQL wrapper UDF validation
            if constraint_type == "linear_reference_range":
                return (
                    f'validate{field_name.title()}LinearReference(col("{field_name}"))'
                )
            elif constraint_type == "unique_items":
                return f'validate{field_name.title()}UniqueItems(col("{field_name}"))'
            elif constraint_type == "json_pointer":
                return f'validate{field_name.title()}JsonPointer(col("{field_name}"))'

        elif constraint.tier == 3:
            # Scala UDF validation - these need special handling in batch validator
            # For now, we'll skip these in the expression list as they require Row-level processing
            pass

        return None
