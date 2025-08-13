"""Spark validation system for Pydantic models with custom constraints.

This module implements a tiered validation strategy for Apache Spark:
- Tier 1 (Pure SQL): Simple patterns, numeric ranges - fastest execution via Catalyst
- Tier 2 (SQL Wrapper UDFs): Complex SQL expressions wrapped for readability
- Tier 3 (Scala UDFs): Complex logic that cannot be expressed in SQL (last resort)

The system generates single-scan batch validation that returns Dataset[ValidationError]
suitable for persistence to tables.
"""

import inspect
import re
import typing
from typing import (
    Annotated,
    Any,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    get_args,
    get_origin,
)

from pydantic import BaseModel
from pydantic.fields import FieldInfo

# Import validation constraints
try:
    from overture.schema.validation.constraints import (
        BaseConstraint,
        CategoryPatternConstraint,
        ConfidenceScoreConstraint,
        CountryCodeConstraint,
        HexColorConstraint,
        ISO8601DateTimeConstraint,
        JSONPointerConstraint,
        LanguageTagConstraint,
        LinearReferenceRangeConstraint,
        NoWhitespaceConstraint,
        PatternConstraint,
        PhoneNumberConstraint,
        RegionCodeConstraint,
        UniqueItemsConstraint,
        WhitespaceConstraint,
        WikidataConstraint,
    )
    from overture.schema.validation.mixin import (
        AnyOfValidator,
        BaseConstraintValidator,
        ExactlyOneOfValidator,
        ExtensionPrefixValidator,
        MinPropertiesValidator,
        NotRequiredIfValidator,
        RequiredIfValidator,
    )
except ImportError:
    # Fallback for when validation package is not available
    BaseConstraint = None
    BaseConstraintValidator = None


class ValidationError:
    """Represents a validation error for Spark processing."""

    def __init__(
        self,
        record_id: str,
        field_name: str,
        constraint_type: str,
        error_message: str,
        field_value: Any = None,
    ):
        self.record_id = record_id
        self.field_name = field_name
        self.constraint_type = constraint_type
        self.error_message = error_message
        self.field_value = field_value


class ValidationConstraint:
    """Represents an extractable validation constraint."""

    def __init__(
        self,
        field_name: str,
        constraint_type: str,
        constraint_params: dict[str, Any],
        tier: int = 1,
        field_python_type: Any = None,
    ):
        self.field_name = field_name
        self.constraint_type = constraint_type
        self.constraint_params = constraint_params
        self.tier = tier  # 1=SQL, 2=SQL wrapper UDF, 3=Scala UDF
        self.field_python_type = (
            field_python_type  # Original Python type for better type detection
        )


class SparkValidationExtractor:
    """Extracts validation constraints from Pydantic models for Spark processing."""

    def __init__(self):
        self.constraint_handlers = {
            # Tier 1: Pure SQL constraints
            "PatternConstraint": self._extract_pattern_constraint,
            "CountryCodeConstraint": self._extract_country_code_constraint,
            "RegionCodeConstraint": self._extract_region_code_constraint,
            "LanguageTagConstraint": self._extract_language_tag_constraint,
            "ISO8601DateTimeConstraint": self._extract_iso8601_constraint,
            "CategoryPatternConstraint": self._extract_category_pattern_constraint,
            "WikidataConstraint": self._extract_wikidata_constraint,
            "PhoneNumberConstraint": self._extract_phone_constraint,
            "HexColorConstraint": self._extract_hex_color_constraint,
            "NoWhitespaceConstraint": self._extract_no_whitespace_constraint,
            "WhitespaceConstraint": self._extract_whitespace_constraint,
            "ConfidenceScoreConstraint": self._extract_confidence_score_constraint,
            # Tier 2: SQL wrapper UDFs
            "LinearReferenceRangeConstraint": self._extract_linear_reference_constraint,
            "UniqueItemsConstraint": self._extract_unique_items_constraint,
            "JSONPointerConstraint": self._extract_json_pointer_constraint,
            # Tier 3: Model-level constraints (complex logic)
            "RequiredIfValidator": self._extract_required_if_constraint,
            "NotRequiredIfValidator": self._extract_not_required_if_constraint,
            "AnyOfValidator": self._extract_any_of_constraint,
            "ExactlyOneOfValidator": self._extract_exactly_one_of_constraint,
            "MinPropertiesValidator": self._extract_min_properties_constraint,
            "ExtensionPrefixValidator": self._extract_extension_prefix_constraint,
        }

    def extract_constraints_from_model(
        self, model_class: type[BaseModel]
    ) -> list[ValidationConstraint]:
        """Extract all validation constraints from a Pydantic model."""
        constraints = []

        # Extract field-level constraints
        for field_name, field_info in model_class.model_fields.items():
            field_constraints = self._extract_field_constraints(
                field_name, field_info, field_info.annotation
            )
            constraints.extend(field_constraints)

        # Extract model-level constraints
        if hasattr(model_class, "__constraints__"):
            model_constraints = getattr(model_class, "__constraints__", [])
            for constraint in model_constraints:
                constraint_type = constraint.__class__.__name__
                if constraint_type in self.constraint_handlers:
                    extracted = self.constraint_handlers[constraint_type](constraint)
                    if extracted:
                        constraints.append(extracted)

        return constraints

    def _extract_field_constraints(
        self, field_name: str, field_info: FieldInfo, field_annotation: Any = None
    ) -> list[ValidationConstraint]:
        """Extract constraints from a single field's type annotation."""
        constraints = []

        # Handle Annotated types with constraints
        if hasattr(field_info, "annotation"):
            constraints.extend(
                self._extract_from_annotation(field_name, field_info.annotation)
            )

            # Also check if the annotation contains NewType with constraints
            constraints.extend(
                self._extract_from_newtype_annotation(field_name, field_info.annotation)
            )

        # Handle Field metadata constraints (stored in field_info.metadata)
        if hasattr(field_info, "metadata") and field_info.metadata:
            for metadata_item in field_info.metadata:
                constraint_type = type(metadata_item).__name__

                # Handle Pydantic constraint objects
                if constraint_type == "MinLen":
                    constraints.append(
                        ValidationConstraint(
                            field_name=field_name,
                            constraint_type="string_min_length",
                            constraint_params={"min_length": metadata_item.min_length},
                            tier=1,
                            field_python_type=field_annotation,
                        )
                    )
                elif constraint_type == "MaxLen":
                    constraints.append(
                        ValidationConstraint(
                            field_name=field_name,
                            constraint_type="string_max_length",
                            constraint_params={"max_length": metadata_item.max_length},
                            tier=1,
                            field_python_type=field_annotation,
                        )
                    )
                elif constraint_type == "Ge":
                    constraints.append(
                        ValidationConstraint(
                            field_name=field_name,
                            constraint_type="numeric_ge",
                            constraint_params={"ge": metadata_item.ge},
                            tier=1,
                        )
                    )
                elif constraint_type == "Le":
                    constraints.append(
                        ValidationConstraint(
                            field_name=field_name,
                            constraint_type="numeric_le",
                            constraint_params={"le": metadata_item.le},
                            tier=1,
                        )
                    )
                elif constraint_type == "Gt":
                    constraints.append(
                        ValidationConstraint(
                            field_name=field_name,
                            constraint_type="numeric_gt",
                            constraint_params={"gt": metadata_item.gt},
                            tier=1,
                        )
                    )
                elif constraint_type == "Lt":
                    constraints.append(
                        ValidationConstraint(
                            field_name=field_name,
                            constraint_type="numeric_lt",
                            constraint_params={"lt": metadata_item.lt},
                            tier=1,
                        )
                    )
                elif constraint_type == "_PydanticGeneralMetadata":
                    # Handle pattern constraints from Field(pattern="...")
                    if hasattr(metadata_item, "pattern") and metadata_item.pattern:
                        constraints.append(
                            ValidationConstraint(
                                field_name=field_name,
                                constraint_type="pattern",
                                constraint_params={
                                    "pattern": metadata_item.pattern,
                                    "error_message": f"Invalid {field_name} format",
                                },
                                tier=1,
                            )
                        )
                # Handle custom constraint objects from overture-schema-validation
                elif hasattr(metadata_item, "__class__"):
                    metadata_constraint_type = metadata_item.__class__.__name__
                    if metadata_constraint_type in self.constraint_handlers:
                        extracted = self.constraint_handlers[metadata_constraint_type](
                            metadata_item, field_name
                        )
                        if extracted:
                            constraints.append(extracted)

        return constraints

    def _extract_from_annotation(
        self, field_name: str, annotation: Any
    ) -> list[ValidationConstraint]:
        """Extract constraints from type annotations."""
        constraints = []

        # Handle Annotated types
        if get_origin(annotation) is Annotated:
            args = get_args(annotation)
            if args:
                # Skip the first arg (the actual type) and look at the annotations
                for arg in args[1:]:
                    if hasattr(arg, "__class__"):
                        constraint_type = arg.__class__.__name__
                        if constraint_type in self.constraint_handlers:
                            extracted = self.constraint_handlers[constraint_type](
                                arg, field_name
                            )
                            if extracted:
                                constraints.append(extracted)

        return constraints

    def _extract_from_newtype_annotation(
        self, field_name: str, annotation: Any
    ) -> list[ValidationConstraint]:
        """Extract constraints from NewType definitions in annotations."""
        constraints = []

        def extract_from_type(type_hint: Any) -> None:
            """Recursively extract constraints from a type hint."""
            # Handle Union types (like Optional[CountryCode])
            if get_origin(type_hint) is Union:
                union_args = get_args(type_hint)
                for arg in union_args:
                    if arg is not type(None):  # Skip None from Optional
                        extract_from_type(arg)
                return

            # Check if this is a NewType
            if hasattr(type_hint, "__supertype__"):
                # This is a NewType, get the underlying type
                underlying_type = type_hint.__supertype__

                # Check if the underlying type is Annotated
                if get_origin(underlying_type) is Annotated:
                    underlying_args = get_args(underlying_type)
                    if underlying_args:
                        # Extract constraints from the Annotated metadata
                        for metadata_item in underlying_args[
                            1:
                        ]:  # Skip first arg (base type)
                            if hasattr(metadata_item, "__class__"):
                                constraint_type = metadata_item.__class__.__name__
                                if constraint_type in self.constraint_handlers:
                                    extracted = self.constraint_handlers[
                                        constraint_type
                                    ](metadata_item, field_name)
                                    if extracted:
                                        constraints.append(extracted)

        extract_from_type(annotation)
        return constraints

    # Tier 1: Pure SQL constraint extractors
    def _extract_pattern_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract pattern constraint for regex validation."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="pattern",
            constraint_params={
                "pattern": constraint.pattern_str,
                "error_message": constraint.error_message,
            },
            tier=1,
        )

    def _extract_country_code_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract ISO 3166-1 alpha-2 country code constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="country_code",
            constraint_params={"pattern": "^[A-Z]{2}$"},
            tier=1,
        )

    def _extract_region_code_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract ISO 3166-2 subdivision code constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="region_code",
            constraint_params={"pattern": "^[A-Z]{2}-[A-Z0-9]{1,3}$"},
            tier=1,
        )

    def _extract_language_tag_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract BCP-47 language tag constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="language_tag",
            constraint_params={
                "pattern": r"^(?:(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}?)|(?:[A-Za-z]{4,8}))(?:-[A-Za-z]{4})?(?:-[A-Za-z]{2}|[0-9]{3})?(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*(?:-[A-WY-Za-wy-z0-9](?:-[A-Za-z0-9]{2,8})+)*$"
            },
            tier=1,
        )

    def _extract_iso8601_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract ISO 8601 datetime constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="iso8601_datetime",
            constraint_params={
                "pattern": r"^([1-9]\d{3})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):([0-5]\d):([0-5]\d|60)(\.\d{1,3})?(Z|[-+]([01]\d|2[0-3]):[0-5]\d)$"
            },
            tier=1,
        )

    def _extract_category_pattern_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract category pattern constraint (snake_case)."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="category_pattern",
            constraint_params={"pattern": "^[a-z0-9]+(_[a-z0-9]+)*$"},
            tier=1,
        )

    def _extract_wikidata_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract Wikidata identifier constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="wikidata_id",
            constraint_params={"pattern": "^Q\\d+$"},
            tier=1,
        )

    def _extract_phone_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract phone number constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="phone_number",
            constraint_params={"pattern": r"^\+\d{1,3}[\s\-\(\)0-9]+$"},
            tier=1,
        )

    def _extract_hex_color_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract hexadecimal color constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="hex_color",
            constraint_params={"pattern": "^#[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$"},
            tier=1,
        )

    def _extract_no_whitespace_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract no whitespace constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="no_whitespace",
            constraint_params={"pattern": "^\\S+$"},
            tier=1,
        )

    def _extract_whitespace_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract whitespace constraint (no leading/trailing)."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="whitespace_trimmed",
            constraint_params={"pattern": r"^(\S.*)?\S$"},
            tier=1,
        )

    def _extract_confidence_score_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract confidence score constraint (0.0 to 1.0)."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="numeric_range",
            constraint_params={"min_value": 0.0, "max_value": 1.0},
            tier=1,
        )

    # Tier 2: SQL wrapper UDF constraint extractors
    def _extract_linear_reference_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract linear reference range constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="linear_reference_range",
            constraint_params={
                "array_length": 2,
                "min_value": 0.0,
                "max_value": 1.0,
                "start_less_than_end": True,
            },
            tier=2,
        )

    def _extract_unique_items_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract unique items constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="unique_items",
            constraint_params={},
            tier=2,
        )

    def _extract_json_pointer_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract JSON pointer constraint."""
        return ValidationConstraint(
            field_name=field_name or "unknown",
            constraint_type="json_pointer",
            constraint_params={},
            tier=2,
        )

    # Tier 3: Model-level constraint extractors
    def _extract_required_if_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract required_if constraint."""
        return ValidationConstraint(
            field_name="__model__",
            constraint_type="required_if",
            constraint_params={
                "condition_field": constraint.condition_field,
                "condition_value": constraint.condition_value,
                "required_fields": constraint.required_fields,
            },
            tier=3,
        )

    def _extract_not_required_if_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract not_required_if constraint."""
        return ValidationConstraint(
            field_name="__model__",
            constraint_type="not_required_if",
            constraint_params={
                "condition_field": constraint.condition_field,
                "condition_value": constraint.condition_value,
                "not_required_fields": constraint.not_required_fields,
            },
            tier=3,
        )

    def _extract_any_of_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract any_of constraint."""
        return ValidationConstraint(
            field_name="__model__",
            constraint_type="any_of",
            constraint_params={"field_names": list(constraint.field_names)},
            tier=3,
        )

    def _extract_exactly_one_of_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract exactly_one_of constraint."""
        return ValidationConstraint(
            field_name="__model__",
            constraint_type="exactly_one_of",
            constraint_params={"field_names": list(constraint.field_names)},
            tier=3,
        )

    def _extract_min_properties_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract min_properties constraint."""
        return ValidationConstraint(
            field_name="__model__",
            constraint_type="min_properties",
            constraint_params={"min_count": constraint.min_count},
            tier=3,
        )

    def _extract_extension_prefix_constraint(
        self, constraint: Any, field_name: str = None
    ) -> ValidationConstraint | None:
        """Extract extension prefix constraint."""
        return ValidationConstraint(
            field_name="__model__",
            constraint_type="extension_prefix",
            constraint_params={"pattern": "^ext_.*$"},
            tier=3,
        )
