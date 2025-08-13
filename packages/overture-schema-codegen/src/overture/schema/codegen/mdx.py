"""MDX documentation generation from Pydantic models."""

import inspect
from typing import Any

from pydantic import BaseModel

from .introspection import (
    FieldInfo,
    extract_fields_recursive,
    get_model_hierarchy,
    is_discriminated_union,
)
from .type_mapping import map_python_type_to_documented


def generate_mdx_documentation(
    model_class_or_union: type[BaseModel] | Any,
    include_hierarchy: bool = False,
    include_field_descriptions: bool = True,
) -> str:
    """Generate MDX documentation for a Pydantic model or discriminated union.

    Args:
        model_class_or_union: The Pydantic model class or discriminated union to document
        include_hierarchy: Whether to include hierarchical structure information
        include_field_descriptions: Whether to include field descriptions

    Returns:
        MDX formatted documentation string
    """
    # Check if it's a discriminated union
    is_union, discriminator, variants = is_discriminated_union(model_class_or_union)

    if is_union and variants and discriminator:
        return _generate_union_mdx(
            model_class_or_union,
            discriminator,
            variants,
            include_field_descriptions,
        )
    else:
        return _generate_model_mdx(
            model_class_or_union,
            include_hierarchy,
            include_field_descriptions,
        )


def _generate_union_mdx(
    union_type: Any,
    discriminator: str,
    variants: list[type[BaseModel]],
    include_field_descriptions: bool,
) -> str:
    """Generate MDX documentation for a discriminated union."""
    mdx_content = []

    # Create a unified title using the union type name if available
    if hasattr(union_type, "__name__") and union_type.__name__ != "Annotated":
        title = union_type.__name__
    else:
        # Extract the actual model name from the Annotated type or use variants
        from typing import get_args

        if hasattr(union_type, "__args__") and get_args(union_type):
            first_arg = get_args(union_type)[0]
            if hasattr(first_arg, "__name__"):
                title = first_arg.__name__
            else:
                # Check if it's a Union and extract a reasonable name
                from typing import get_origin

                if get_origin(first_arg):
                    # Try to extract from variants
                    title = "Segment"  # Hardcode for now, can be made smarter
                else:
                    variant_names = [v.__name__ for v in variants]
                    title = f"Discriminated Union: {', '.join(variant_names)}"
        else:
            variant_names = [v.__name__ for v in variants]
            title = f"Discriminated Union: {', '.join(variant_names)}"

    mdx_content.append(f"# {title}")
    mdx_content.append("")

    # Add docstring if available
    if hasattr(union_type, "__doc__") and union_type.__doc__:
        mdx_content.append(union_type.__doc__)
        mdx_content.append("")

    # Generate unified fields table (similar to Spark Scala approach)
    unified_fields = _generate_unified_fields_for_union(discriminator, variants)

    if unified_fields:
        mdx_content.extend(
            _format_fields_as_mdx(unified_fields, include_field_descriptions)
        )

    return "\n".join(mdx_content)


def _generate_unified_fields_for_union(
    discriminator: str,
    variants: list[type[BaseModel]],
) -> list[FieldInfo]:
    """Generate a unified field list for a discriminated union.

    Creates a runtime mixin class that combines all variant fields,
    then uses standard Pydantic field extraction on that unified model.
    """
    from typing import Any, Optional

    from pydantic import Field

    from .introspection import extract_fields_recursive

    # Create a dynamic class that mixes in all variants
    class_name = f"Unified{''.join(v.__name__ for v in variants)}"

    # Collect all unique fields from variants
    all_field_definitions = {}

    # Add discriminator field first with proper annotation
    discriminator_values = [get_discriminator_value(v, discriminator) for v in variants]
    discriminator_annotation = str
    all_field_definitions[discriminator] = (
        discriminator_annotation,
        Field(
            description=f"Discriminator field that determines the variant type. Values: {', '.join(discriminator_values)}"
        ),
    )

    # Process each variant to collect field definitions
    for variant in variants:
        for field_name, field_info in variant.model_fields.items():
            # Skip discriminator as we handle it specially
            if field_name == discriminator:
                continue

            if field_name not in all_field_definitions:
                # Make all variant-specific fields optional in the unified view
                original_annotation = field_info.annotation

                # Convert to Optional if not already
                if not _is_optional_annotation(original_annotation):
                    optional_annotation = Optional[original_annotation]
                else:
                    optional_annotation = original_annotation

                # Create field definition with proper default and description
                field_kwargs = {}
                if field_info.description:
                    field_kwargs["description"] = field_info.description
                if hasattr(field_info, "alias") and field_info.alias:
                    field_kwargs["alias"] = field_info.alias

                # Set default to None for variant-specific fields
                if field_info.default is not None and "PydanticUndefined" not in str(
                    field_info.default
                ):
                    field_kwargs["default"] = field_info.default
                else:
                    field_kwargs["default"] = None

                all_field_definitions[field_name] = (
                    optional_annotation,
                    Field(**field_kwargs),
                )

    # Create the unified model class dynamically
    unified_model = type(
        class_name,
        (BaseModel,),
        {
            "__annotations__": {
                name: annotation
                for name, (annotation, _) in all_field_definitions.items()
            },
            **{
                name: field_def
                for name, (_, field_def) in all_field_definitions.items()
            },
        },
    )

    # Extract fields from the unified model using standard introspection
    return extract_fields_recursive(unified_model)


def _is_optional_annotation(annotation: Any) -> bool:
    """Check if an annotation is already Optional/Union with None."""
    import types
    from typing import Union, get_args, get_origin

    # Handle new union syntax (Python 3.10+)
    if isinstance(annotation, types.UnionType):
        return type(None) in annotation.__args__

    # Handle typing.Union
    origin = get_origin(annotation)
    if origin is Union:
        args = get_args(annotation)
        return type(None) in args

    return False


def get_discriminator_value(variant: type[BaseModel], discriminator: str) -> str:
    """Extract the discriminator value for a variant."""
    try:
        # Get the field info for the discriminator
        if discriminator in variant.model_fields:
            field_info = variant.model_fields[discriminator]
            # For Literal types, get the actual value
            if hasattr(field_info, "annotation"):
                annotation = field_info.annotation
                # Handle Literal types
                from typing import Literal, get_args, get_origin

                if get_origin(annotation) is Literal:
                    args = get_args(annotation)
                    if args:
                        # Handle enum values in Literal
                        value = args[0]
                        if hasattr(value, "value"):
                            return str(value.value)
                        return str(value)
                # For enums, try to get the value
                if hasattr(annotation, "__members__"):
                    # It's an enum, return the first value's string representation
                    first_member = list(annotation.__members__.values())[0]
                    if hasattr(first_member, "value"):
                        return str(first_member.value)
                    return str(first_member)

        # Fallback to variant name in lowercase
        return variant.__name__.lower().replace("segment", "")
    except Exception:
        # Final fallback
        return variant.__name__.lower()


def _generate_model_mdx(
    model_class: type[BaseModel],
    include_hierarchy: bool,
    include_field_descriptions: bool,
) -> str:
    """Generate MDX documentation for a single Pydantic model."""
    if not (inspect.isclass(model_class) and issubclass(model_class, BaseModel)):
        raise ValueError(f"Expected a Pydantic BaseModel class, got {model_class}")

    mdx_content = []

    # Title
    mdx_content.append(f"# {model_class.__name__}")
    mdx_content.append("")

    # Model description from docstring
    docstring = inspect.getdoc(model_class)
    if docstring:
        mdx_content.append(docstring)
        mdx_content.append("")

    # Fields section
    if include_hierarchy:
        hierarchy = get_model_hierarchy(model_class)
        mdx_content.extend(
            _format_hierarchy_as_mdx(hierarchy, include_field_descriptions)
        )
    else:
        try:
            fields = extract_fields_recursive(model_class)
            mdx_content.extend(
                _format_fields_as_mdx(fields, include_field_descriptions)
            )
        except Exception as e:
            mdx_content.append("## Fields")
            mdx_content.append("")
            mdx_content.append(f"Error extracting fields: {e}")
            mdx_content.append("")

    return "\n".join(mdx_content)


def _format_fields_as_mdx(
    fields: list[FieldInfo],
    include_descriptions: bool,
) -> list[str]:
    """Format a list of fields as MDX table content."""
    content = []

    if not fields:
        return content

    content.append("## Fields")
    content.append("")

    # Create table header
    content.append("| Name | Type | Description |")
    content.append("|-----:|:----:|-------------|")

    for field in fields:
        # Format field name with jq-style array notation
        field_name = _format_field_name_with_arrays(field.name)

        if field.is_discriminated_union:
            # Handle discriminated union
            type_info = "Discriminated Union"
            if field.union_variants:
                variant_names = [v.__name__ for v in field.union_variants]
                type_info += f" ({', '.join(variant_names)})"

            description = field.description or ""
            if field.discriminator_field:
                description += f" Discriminator: `{field.discriminator_field}`"
        else:
            # Regular field - use documented type mapping
            type_info = map_python_type_to_documented(
                field.python_type,
                field.is_nullable or not field.is_required,
                field.name,
            )

            description = field.description or ""

            # Add default value if present and meaningful
            if not field.is_required and field.default_value is not None:
                default_str = repr(field.default_value)
                # Don't show internal Pydantic values
                if (
                    "PydanticUndefined" not in default_str
                    and "Ellipsis" not in default_str
                ):
                    description += f" Default: `{default_str}`"

        # Escape pipes and newlines in description for table format
        if description:
            description = (
                description.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
            )
        else:
            description = ""

        # Add table row
        content.append(f"| `{field_name}` | {type_info} | {description} |")

    content.append("")
    return content


def _format_field_name_with_arrays(field_name: str) -> str:
    """Convert field names with dot notation to jq-style array notation."""
    # Handle known list/array fields that should use jq notation
    # These are common patterns in the Overture schema
    array_patterns = {
        "names.rules": "names.rules[]",
        "sources": "sources[]",
        "names.common": "names.common",  # This is a dict, not an array
    }

    # Check for exact matches first
    for pattern, replacement in array_patterns.items():
        if field_name.startswith(pattern + "."):
            # Replace the pattern part and keep the rest
            remaining = field_name[len(pattern) + 1 :]
            return f"{replacement}.{remaining}"
        elif field_name == pattern and replacement.endswith("[]"):
            return replacement

    # If no special pattern matches, return as-is
    return field_name


def _format_hierarchy_as_mdx(
    hierarchy: dict[str, Any],
    include_descriptions: bool,
) -> list[str]:
    """Format hierarchical model structure as MDX content."""
    content = []

    def _format_hierarchy_recursive(h: dict[str, Any], level: int = 2) -> None:
        # Model header
        header_prefix = "#" * level
        content.append(f"{header_prefix} {h['name']}")
        content.append("")

        # Fields
        if h["fields"]:
            content.append(f"{'#' * (level + 1)} Fields")
            content.append("")

            for field_name, field_info in h["fields"].items():
                type_str = field_info["type"]

                # Build field entry
                field_entry = f"- **`{field_name}`**"
                metadata_parts = []
                metadata_parts.append(f"`{type_str}`")
                if field_info["required"]:
                    metadata_parts.append("**required**")
                else:
                    metadata_parts.append("*optional*")
                if field_info["nullable"]:
                    metadata_parts.append("*nullable*")

                field_entry += f" ({', '.join(metadata_parts)})"

                content.append(field_entry)

                # Field description
                if include_descriptions and field_info.get("description"):
                    content.append(f"  {field_info['description']}")

                # Nested model reference
                if "nested_model" in field_info:
                    nested_name = field_info["nested_model"]
                    content.append(f"  *See: [{nested_name}](#{nested_name.lower()})*")

                content.append("")

        # Process nested models
        if h["nested_models"]:
            for nested_hierarchy in h["nested_models"].values():
                _format_hierarchy_recursive(nested_hierarchy, level + 1)

    _format_hierarchy_recursive(hierarchy)
    return content
