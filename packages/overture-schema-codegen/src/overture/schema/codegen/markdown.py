"""Markdown documentation generation from Pydantic models."""

import enum
import inspect
import os
from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel

from .introspection import (
    FieldInfo,
    extract_fields_recursive,
    get_model_hierarchy,
    is_discriminated_union,
)
from .type_mapping import get_enum_examples, map_python_type_to_documented


def generate_markdown_documentation(
    model_class_or_union: type[BaseModel] | Any,
    include_hierarchy: bool = False,
    include_field_descriptions: bool = True,
    current_theme: str | None = None,
) -> str:
    """Generate Markdown documentation for a Pydantic model or discriminated union.

    Args:
        model_class_or_union: The Pydantic model class or discriminated union to document
        include_hierarchy: Whether to include hierarchical structure information
        include_field_descriptions: Whether to include field descriptions

    Returns:
        Markdown formatted documentation string
    """
    # Check if it's a discriminated union
    is_union, discriminator, variants = is_discriminated_union(model_class_or_union)

    if is_union and variants and discriminator:
        return _generate_union_markdown(
            model_class_or_union,
            discriminator,
            variants,
            include_field_descriptions,
            current_theme,
        )
    else:
        return _generate_model_markdown(
            model_class_or_union,
            include_hierarchy,
            include_field_descriptions,
            current_theme,
        )


def _generate_union_markdown(
    union_type: Any,
    discriminator: str,
    variants: list[type[BaseModel]],
    include_field_descriptions: bool,
    current_theme: str | None = None,
) -> str:
    """Generate Markdown documentation for a discriminated union."""
    markdown_content = []

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

    markdown_content.append(f"# {title}")
    markdown_content.append("")

    # Add docstring if available
    if hasattr(union_type, "__doc__") and union_type.__doc__:
        markdown_content.append(union_type.__doc__)
        markdown_content.append("")

    # Generate unified fields table (similar to Spark Scala approach)
    unified_fields = _generate_unified_fields_for_union(discriminator, variants)

    if unified_fields:
        markdown_content.extend(
            _format_fields_as_markdown(
                unified_fields, include_field_descriptions, current_theme
            )
        )

    # Add examples section for union variants
    try:
        all_examples = []
        for variant in variants:
            examples = _load_examples_for_model(variant)
            if examples:
                all_examples.extend(examples)

        if all_examples:
            markdown_content.extend(_format_examples_as_markdown(all_examples, title))
    except Exception:
        # If we can't load examples, just continue without them
        pass

    return "\n".join(markdown_content)


def _generate_unified_fields_for_union(
    discriminator: str,
    variants: list[type[BaseModel]],
) -> list[FieldInfo]:
    """Generate a unified field list for a discriminated union.

    Creates a runtime mixin class that combines all variant fields,
    then uses standard Pydantic field extraction on that unified model.
    """
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
                    optional_annotation = original_annotation | None
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
    from typing import Union

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


def _generate_model_markdown(
    model_class: type[BaseModel],
    include_hierarchy: bool,
    include_field_descriptions: bool,
    current_theme: str | None = None,
) -> str:
    """Generate Markdown documentation for a single Pydantic model."""
    if not (inspect.isclass(model_class) and issubclass(model_class, BaseModel)):
        raise ValueError(f"Expected a Pydantic BaseModel class, got {model_class}")

    markdown_content = []

    # Title
    markdown_content.append(f"# {model_class.__name__}")
    markdown_content.append("")

    # Model description from docstring
    docstring = inspect.getdoc(model_class)
    if docstring:
        markdown_content.append(docstring)
        markdown_content.append("")

    # Fields section
    if include_hierarchy:
        hierarchy = get_model_hierarchy(model_class)
        markdown_content.extend(
            _format_hierarchy_as_markdown(
                hierarchy, include_field_descriptions, current_theme
            )
        )
    else:
        try:
            fields = extract_fields_recursive(model_class)
            markdown_content.extend(
                _format_fields_as_markdown(
                    fields, include_field_descriptions, current_theme
                )
            )
        except Exception as e:
            markdown_content.append("## Fields")
            markdown_content.append("")
            markdown_content.append(f"Error extracting fields: {e}")
            markdown_content.append("")

    # Add examples section
    try:
        examples = _load_examples_for_model(model_class)
        if examples:
            markdown_content.extend(
                _format_examples_as_markdown(
                    examples, model_class.__name__, model_class
                )
            )
    except Exception:
        # If we can't load examples, just continue without them
        # This ensures the documentation generation doesn't fail
        pass

    return "\n".join(markdown_content)


def _format_fields_as_markdown(
    fields: list[FieldInfo],
    include_descriptions: bool,
    current_theme: str | None = None,
) -> list[str]:
    """Format a list of fields as Markdown table content."""
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
                current_theme,
            )

            description = field.description or ""

            # Add enum examples for string enums
            try:
                import enum

                if (
                    inspect.isclass(field.python_type)
                    and issubclass(field.python_type, enum.Enum)
                    and issubclass(field.python_type, str)
                ):
                    enum_examples = get_enum_examples(field.python_type, 3)
                    if enum_examples:
                        if description and not description.endswith(" "):
                            description += " "
                        # Format examples with proper punctuation
                        examples_str = ", ".join(f"`{ex}`" for ex in enum_examples)
                        if len(enum_examples) == 3 and len(list(field.python_type)) > 3:
                            examples_str += ", ..."
                        description += f"Examples: {examples_str}"
            except (ImportError, TypeError, AttributeError):
                pass

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


def _format_hierarchy_as_markdown(
    hierarchy: dict[str, Any],
    include_descriptions: bool,
    current_theme: str | None = None,
) -> list[str]:
    """Format hierarchical model structure as Markdown content."""
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


def generate_enum_markdown_documentation(enum_class: type[enum.Enum]) -> str:
    """Generate Markdown documentation for an Enum class.

    Args:
        enum_class: The Enum class to document

    Returns:
        Markdown formatted documentation string
    """
    if not (inspect.isclass(enum_class) and issubclass(enum_class, enum.Enum)):
        raise ValueError(f"Expected an Enum class, got {enum_class}")

    markdown_content = []

    # Title
    markdown_content.append(f"# {enum_class.__name__}")
    markdown_content.append("")

    # Enum description from docstring
    docstring = inspect.getdoc(enum_class)
    if docstring:
        markdown_content.append(docstring)
        markdown_content.append("")

    # Values section
    markdown_content.append("## Values")
    markdown_content.append("")

    # Create simple list of values
    for enum_member in enum_class:
        value = enum_member.value
        # Add each value as a code block
        markdown_content.append(f"- `{value}`")

    markdown_content.append("")
    return "\n".join(markdown_content)


def _load_examples_for_model(model_class: type[BaseModel]) -> list[dict[str, Any]]:
    """Load example data for a model from theme package pyproject.toml files.

    Args:
        model_class: The Pydantic model class to find examples for

    Returns:
        List of example dictionaries for the model
    """
    try:
        # Try to load tomllib (Python 3.11+) or tomli as fallback
        try:
            import tomllib

            toml_loads = tomllib.loads
            toml_open_mode = "rb"
        except ImportError:
            try:
                import tomli

                toml_loads = tomli.loads
                toml_open_mode = "rb"
            except ImportError:
                # Fallback to toml library if available
                import toml

                toml_loads = toml.loads
                toml_open_mode = "r"
    except ImportError:
        # No TOML library available
        return []

    # Get the model class name
    model_name = model_class.__name__

    # Try to find the theme from the model's module path
    theme_name = _extract_theme_from_model_module(model_class)
    if not theme_name:
        return []

    # Look for pyproject.toml in the theme package
    examples_data = _load_theme_examples(theme_name, toml_loads, toml_open_mode)

    # Return examples for this specific model
    return examples_data.get(model_name, [])


def _extract_theme_from_model_module(model_class: type[BaseModel]) -> str | None:
    """Extract theme name from a model's module path."""
    if not hasattr(model_class, "__module__"):
        return None

    module_parts = model_class.__module__.split(".")
    for part in module_parts:
        if part.endswith("-theme"):
            return part.replace("-theme", "")
        elif part in [
            "transportation",
            "buildings",
            "places",
            "addresses",
            "base",
            "divisions",
        ]:
            return part
    return None


def _load_theme_examples(
    theme_name: str, toml_loads: Any, toml_open_mode: str
) -> dict[str, list[dict[str, Any]]]:
    """Load example data from a theme package's pyproject.toml file.

    Args:
        theme_name: The theme name (e.g., 'addresses', 'buildings')
        toml_loads: The TOML parsing function to use
        toml_open_mode: File open mode ('rb' or 'r')

    Returns:
        Dictionary mapping model names to lists of examples
    """
    # Look for the theme package directory in the current workspace
    theme_package_name = f"overture-schema-{theme_name}-theme"

    # Try common locations for the pyproject.toml file
    possible_paths = [
        f"packages/{theme_package_name}/pyproject.toml",
        f"../packages/{theme_package_name}/pyproject.toml",
        f"../../packages/{theme_package_name}/pyproject.toml",
        f"{theme_package_name}/pyproject.toml",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            try:
                if toml_open_mode == "rb":
                    with open(path, "rb") as f:
                        content = f.read()
                    # tomli.loads expects str, not bytes
                    if isinstance(content, bytes):
                        content = content.decode("utf-8")
                    data = toml_loads(content)
                else:
                    with open(path) as f:
                        content = f.read()
                    data = toml_loads(content)

                return data.get("examples", {})
            except Exception:
                # If we can't parse the file, continue to next path
                continue

    return {}


def _format_examples_as_markdown(
    examples: list[dict[str, Any]],
    model_name: str,
    model_class: type[BaseModel] | None = None,
) -> list[str]:
    """Format example data as markdown table content.

    Args:
        examples: List of example dictionaries
        model_name: Name of the model for the section header

    Returns:
        List of markdown content lines
    """
    if not examples:
        return []

    content = []
    content.append("## Examples")
    content.append("")

    for i, example in enumerate(examples, 1):
        # Add example header if there are multiple examples
        if len(examples) > 1:
            content.append(f"### Example {i}")
            content.append("")

        # Create table with flattened example data
        content.append("| Column | Value |")
        content.append("|-------:|-------|")

        # Flatten the example data and format as table rows
        flattened = _flatten_example_dict(example)

        # Sort using model annotations if available, otherwise alphabetically
        if model_class is not None:
            sort_key = _get_field_sort_key_from_model(model_class)
            sorted_items = sorted(flattened.items(), key=sort_key)
        else:
            sorted_items = sorted(flattened.items())

        for field_name, value in sorted_items:
            # Format the value for display
            formatted_value = _format_example_value(value)

            # Escape pipes in values
            formatted_value = formatted_value.replace("|", "\\|")

            content.append(f"| `{field_name}` | {formatted_value} |")

        content.append("")

    return content


def _flatten_example_dict(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten nested dictionary into dot-notation keys.

    Args:
        data: Dictionary to flatten
        prefix: Prefix for keys (for recursive calls)

    Returns:
        Flattened dictionary
    """
    flattened = {}

    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            # Skip special nested objects like bbox for now - they're not part of the main model
            if key in ["bbox"]:
                continue
            # Recursively flatten nested dictionaries
            flattened.update(_flatten_example_dict(value, full_key))
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            # For lists of dictionaries, show the structure with array notation
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    flattened.update(_flatten_example_dict(item, f"{full_key}[{i}]"))
                else:
                    flattened[f"{full_key}[{i}]"] = item
        else:
            flattened[full_key] = value

    return flattened


def _format_example_value(value: Any) -> str:
    """Format an example value for display in markdown table.

    Args:
        value: The value to format

    Returns:
        Formatted string representation
    """
    if value is None or value == "null":
        return "`null`"
    elif isinstance(value, bool):
        return f"`{str(value).lower()}`"
    elif isinstance(value, str):
        # For long strings like geometry, truncate them
        if len(value) > 100:
            return f"`{value[:100]}...`"
        elif len(value):
            return f"`{value}`"
        else:
            return ""
    elif isinstance(value, int | float):
        return f"`{value}`"
    elif isinstance(value, list):
        if not value:
            return "`[]`"
        # Show first few items
        items = [str(v) for v in value[:3]]
        if len(value) > 3:
            items.append("...")
        return f"`[{', '.join(items)}]`"
    else:
        return f"`{str(value)}`"


class SortOrder:
    """Annotation class for specifying field sort order in documentation.

    Usage:
        field_name: Annotated[str, SortOrder(10), Field(description="...")]
    """

    def __init__(self, order: int):
        self.order = order


def _get_field_sort_order(model_class: type[BaseModel], field_name: str) -> int:
    """Extract sort order from field annotations.

    Args:
        model_class: The Pydantic model class
        field_name: Name of the field to get sort order for

    Returns:
        Sort order integer, or 999 if no sort order is specified
    """
    try:
        # Get the field's annotation from the model
        if (
            hasattr(model_class, "__annotations__")
            and field_name in model_class.__annotations__
        ):
            annotation = model_class.__annotations__[field_name]

            # Check if it's an Annotated type
            if get_origin(annotation) is Annotated:
                args = get_args(annotation)
                if len(args) >= 2:
                    # Look through metadata for SortOrder
                    metadata = args[1:]
                    for item in metadata:
                        if isinstance(item, SortOrder):
                            return item.order
    except Exception:
        # If anything goes wrong, just return default
        pass

    return 999  # Default sort order for fields without explicit ordering


def _get_field_sort_key_from_model(model_class: type[BaseModel]) -> callable:
    """Create a sort key function that uses field annotations from the model.

    Args:
        model_class: The Pydantic model class to extract sort orders from

    Returns:
        Function that can be used as a key for sorted()
    """
    # Get field definition order from the model
    field_definition_order = {}
    if hasattr(model_class, "__annotations__"):
        for i, field_name in enumerate(model_class.__annotations__.keys()):
            field_definition_order[field_name] = i

    def sort_key(field_tuple: tuple[str, Any]) -> tuple[int, int, str]:
        field_name = field_tuple[0]

        # Handle nested field names by getting the base field name
        base_field_name = field_name.split("[")[0].split(".")[0]

        # Get sort order from model annotations
        sort_order = _get_field_sort_order(model_class, base_field_name)

        # Get definition order for tiebreaking
        definition_order = field_definition_order.get(base_field_name, 999)

        # Return tuple for sorting: (sort_order, definition_order, field_name for final tiebreaker)
        return (sort_order, definition_order, field_name)

    return sort_key
