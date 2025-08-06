"""PlantUML class diagram generator from Pydantic models."""

import re
from typing import Any, Dict, List, Set

from pydantic import BaseModel

from .introspection import (
    FieldInfo,
    extract_fields_recursive,
    get_model_hierarchy,
    is_discriminated_union,
)


def generate_combined_plantuml_diagram(
    models: list[type[BaseModel] | Any],
    include_nested: bool = True,
    show_field_types: bool = True,
    show_descriptions: bool = False,
) -> str:
    """Generate a combined PlantUML diagram for multiple models without duplicates.

    Args:
        models: List of Pydantic model classes or discriminated unions
        include_nested: Whether to include nested model classes
        show_field_types: Whether to show field types in the diagram
        show_descriptions: Whether to include field descriptions as notes

    Returns:
        Combined PlantUML class diagram as string
    """
    lines = [
        "@startuml",
        "!define LIGHTYELLOW #FFFACD",
        "!define LIGHTBLUE #E6F3FF",
        "!define LIGHTGREEN #E6FFE6",
        "",
        "' Combined diagram for multiple models",
        "",
    ]

    processed_models: set[str] = set()
    relationships: set[str] = set()

    # Process each model
    for model_class_or_union in models:
        is_union, discriminator, variants = is_discriminated_union(model_class_or_union)

        if is_union and variants and discriminator:
            # Handle discriminated union
            union_name = f"Union_{('_'.join(v.__name__ for v in variants))}"

            if union_name not in processed_models:
                lines.extend(
                    [
                        f"abstract class {union_name} {{",
                        f"  +{discriminator}: string",
                        "}",
                        f"{union_name} <<discriminated union>>",
                        "",
                    ]
                )
                processed_models.add(union_name)

            # Process each variant
            for variant in variants:
                if include_nested:
                    hierarchy = get_model_hierarchy(variant)
                    _generate_hierarchy_classes(
                        hierarchy,
                        lines,
                        relationships,
                        show_field_types,
                        show_descriptions,
                        processed_models,
                    )
                else:
                    variant_lines = _generate_single_class(
                        variant, show_field_types, show_descriptions, processed_models
                    )
                    lines.extend(variant_lines)
                    lines.append("")

                # Add inheritance relationship
                relationships.add(f"{union_name} <|-- {variant.__name__}")
        else:
            # Handle regular model
            if include_nested:
                hierarchy = get_model_hierarchy(model_class_or_union)
                _generate_hierarchy_classes(
                    hierarchy,
                    lines,
                    relationships,
                    show_field_types,
                    show_descriptions,
                    processed_models,
                )
            else:
                model_lines = _generate_single_class(
                    model_class_or_union,
                    show_field_types,
                    show_descriptions,
                    processed_models,
                )
                lines.extend(model_lines)
                lines.append("")

    # Add relationships
    if relationships:
        lines.append("")
        lines.append("' Relationships")
        lines.extend(sorted(relationships))

    lines.extend(["", "@enduml"])
    return "\n".join(lines)


def generate_plantuml_class_diagram(
    model_class_or_union: type[BaseModel] | Any,
    include_nested: bool = True,
    show_field_types: bool = True,
    show_descriptions: bool = False,
) -> str:
    """Generate PlantUML class diagram from a Pydantic model.

    Args:
        model_class_or_union: Pydantic model class or discriminated union
        include_nested: Whether to include nested model classes
        show_field_types: Whether to show field types in the diagram
        show_descriptions: Whether to include field descriptions as notes

    Returns:
        PlantUML class diagram as string
    """
    is_union, discriminator, variants = is_discriminated_union(model_class_or_union)

    if is_union and variants and discriminator:
        return _generate_union_diagram(
            variants, discriminator, show_field_types, show_descriptions
        )
    else:
        return _generate_model_diagram(
            model_class_or_union, include_nested, show_field_types, show_descriptions
        )


def _generate_union_diagram(
    variants: list[type[BaseModel]],
    discriminator: str,
    show_field_types: bool,
    show_descriptions: bool,
) -> str:
    """Generate PlantUML diagram for discriminated union."""
    lines = [
        "@startuml",
        "!define LIGHTYELLOW #FFFACD",
        "!define LIGHTBLUE #E6F3FF",
        "!define LIGHTGREEN #E6FFE6",
        "",
        "' Discriminated Union Diagram",
        f"' Discriminator field: {discriminator}",
        "",
    ]

    # Create abstract base for the union
    union_name = f"Union_{('_'.join(v.__name__ for v in variants))}"
    lines.extend(
        [
            f"abstract class {union_name} {{",
            f"  +{discriminator}: string",
            "}",
            f"{union_name} <<discriminated union>>",
            "",
        ]
    )

    # Generate each variant
    processed_models = set()
    for variant in variants:
        variant_lines = _generate_single_class(
            variant, show_field_types, show_descriptions, processed_models
        )
        lines.extend(variant_lines)
        lines.append("")

        # Add inheritance relationship
        lines.append(f"{union_name} <|-- {variant.__name__}")

    lines.extend(["", "@enduml"])
    return "\n".join(lines)


def _generate_model_diagram(
    model_class: type[BaseModel],
    include_nested: bool,
    show_field_types: bool,
    show_descriptions: bool,
) -> str:
    """Generate PlantUML diagram for a single model with optional nested models."""
    lines = [
        "@startuml",
        "!define LIGHTYELLOW #FFFACD",
        "!define LIGHTBLUE #E6F3FF",
        "!define LIGHTGREEN #E6FFE6",
        "",
        f"' Class diagram for {model_class.__name__}",
        "",
    ]

    processed_models: set[str] = set()
    relationships: set[str] = set()

    if include_nested:
        # Use hierarchy to get all related models
        hierarchy = get_model_hierarchy(model_class)
        _generate_hierarchy_classes(
            hierarchy,
            lines,
            relationships,
            show_field_types,
            show_descriptions,
            processed_models,
        )
    else:
        # Just generate the single class
        class_lines = _generate_single_class(
            model_class, show_field_types, show_descriptions, processed_models
        )
        lines.extend(class_lines)

    # Add relationships
    if relationships:
        lines.append("")
        lines.append("' Relationships")
        lines.extend(sorted(relationships))

    lines.extend(["", "@enduml"])
    return "\n".join(lines)


def _generate_hierarchy_classes(
    hierarchy: dict[str, Any],
    lines: list[str],
    relationships: set[str],
    show_field_types: bool,
    show_descriptions: bool,
    processed_models: set[str],
) -> None:
    """Recursively generate classes from model hierarchy."""
    model_name = hierarchy["name"]

    if model_name in processed_models:
        return
    processed_models.add(model_name)

    # Generate this class
    lines.append(f"class {model_name} {{")

    # Add fields
    for field_name, field_info in hierarchy["fields"].items():
        field_line = _format_field_for_plantuml(
            field_name, field_info, show_field_types
        )
        lines.append(f"  {field_line}")

        # Check for nested model relationships
        if field_info.get("nested_model"):
            nested_name = field_info["nested_model"]
            relationships.add(f"{model_name} --> {nested_name}")

    lines.extend(["}", f"{model_name} <<Pydantic Model>>", ""])

    # Add field descriptions as notes if requested
    if show_descriptions:
        for field_name, field_info in hierarchy["fields"].items():
            if field_info.get("description"):
                clean_desc = _clean_description(field_info["description"])
                lines.append(f"note right of {model_name}::{field_name} : {clean_desc}")

    # Process nested models
    for nested_name, nested_hierarchy in hierarchy.get("nested_models", {}).items():
        _generate_hierarchy_classes(
            nested_hierarchy,
            lines,
            relationships,
            show_field_types,
            show_descriptions,
            processed_models,
        )


def _generate_single_class(
    model_class: type[BaseModel],
    show_field_types: bool,
    show_descriptions: bool,
    processed_models: set[str],
) -> list[str]:
    """Generate PlantUML for a single class without nested relationships."""
    class_name = model_class.__name__

    if class_name in processed_models:
        return [f"' {class_name} already defined"]
    processed_models.add(class_name)

    lines = [f"class {class_name} {{"]

    # Add fields
    for field_name, field_info in model_class.model_fields.items():
        field_line = _format_field_for_model_field(
            field_name, field_info, show_field_types
        )
        lines.append(f"  {field_line}")

    lines.extend(
        [
            "}",
            f"{class_name} <<Pydantic Model>>",
        ]
    )

    # Add field descriptions as notes if requested
    if show_descriptions:
        for field_name, field_info in model_class.model_fields.items():
            if field_info.description:
                clean_desc = _clean_description(field_info.description)
                lines.append(f"note right of {class_name}::{field_name} : {clean_desc}")

    return lines


def _format_field_for_plantuml(
    field_name: str,
    field_info: dict[str, Any],
    show_field_types: bool,
) -> str:
    """Format a field from hierarchy info for PlantUML."""
    # Determine field visibility (+ for required, - for optional)
    visibility = "+" if field_info.get("required", False) else "-"

    if show_field_types:
        type_str = _simplify_type_name(field_info.get("type", "unknown"))
        return f"{visibility}{field_name}: {type_str}"
    else:
        return f"{visibility}{field_name}"


def _format_field_for_model_field(
    field_name: str,
    field_info: Any,
    show_field_types: bool,
) -> str:
    """Format a field from Pydantic FieldInfo for PlantUML."""
    # Determine field visibility
    visibility = "+" if field_info.is_required() else "-"

    if show_field_types:
        type_str = _simplify_type_name(str(field_info.annotation))
        return f"{visibility}{field_name}: {type_str}"
    else:
        return f"{visibility}{field_name}"


def _simplify_type_name(type_str: str) -> str:
    """Simplify complex type names for better readability in diagrams."""
    # Remove common prefixes
    type_str = re.sub(r"typing\.", "", type_str)
    type_str = re.sub(r"<class '([^']+)'>", r"\1", type_str)
    type_str = re.sub(r"overture\.schema\.[^.]+\.", "", type_str)

    # Simplify common patterns
    type_str = re.sub(r"Union\[([^,]+), None\]", r"Optional[\1]", type_str)
    type_str = re.sub(r"Union\[([^,]+), type\[None\]\]", r"Optional[\1]", type_str)
    type_str = re.sub(r"\| None", "", type_str)  # Python 3.10+ union syntax

    # Truncate very long type names
    if len(type_str) > 50:
        type_str = type_str[:47] + "..."

    return type_str


def _clean_description(description: str) -> str:
    """Clean description text for use in PlantUML notes."""
    if not description:
        return ""

    # Remove extra whitespace and line breaks
    cleaned = " ".join(description.split())

    # Escape special PlantUML characters
    cleaned = cleaned.replace(":", "\\:")
    cleaned = cleaned.replace("{", "\\{")
    cleaned = cleaned.replace("}", "\\}")

    # Truncate very long descriptions
    if len(cleaned) > 100:
        cleaned = cleaned[:97] + "..."

    return cleaned


def generate_plantuml_sequence_diagram(
    operations: list[str], title: str = "Model Processing Sequence"
) -> str:
    """Generate PlantUML sequence diagram for model processing operations.

    This could be useful for showing the flow of code generation operations.
    """
    lines = [
        "@startuml",
        f"title {title}",
        "",
        "participant CLI",
        "participant Introspection",
        "participant Generator",
        "participant Output",
        "",
    ]

    for i, operation in enumerate(operations, 1):
        # Simple mapping of operations to sequence steps
        if "load" in operation.lower():
            lines.append(f"CLI -> Introspection: {operation}")
        elif "generate" in operation.lower():
            lines.append(f"Introspection -> Generator: {operation}")
        elif "output" in operation.lower():
            lines.append(f"Generator -> Output: {operation}")
        else:
            lines.append(f"note over CLI, Output: {operation}")

    lines.extend(["", "@enduml"])
    return "\n".join(lines)
