"""Error formatting and grouping for validation errors."""

from typing import Any

from rich.console import Console

from .type_analysis import (
    UnionMetadata,
    create_structural_tuple,
    extract_discriminator_path,
    introspect_union,
)


def group_errors_by_discriminator(
    errors: list[dict[str, Any]],
    metadata: UnionMetadata,
) -> dict[tuple[str | int, ...], list[dict[str, Any]]]:
    """Group validation errors by their discriminator path.

    Args:
        errors: List of Pydantic validation error dicts
        metadata: Pre-computed UnionMetadata from introspect_union()

    Returns:
        Dictionary mapping discriminator paths to lists of errors
    """
    groups: dict[tuple[str | int, ...], list[dict[str, Any]]] = {}

    for error in errors:
        loc = error["loc"]
        try:
            structural = create_structural_tuple(loc, metadata)
            disc_path = extract_discriminator_path(loc, structural)
            if disc_path not in groups:
                groups[disc_path] = []
            groups[disc_path].append(error)
        except Exception:
            # If structural analysis fails, group under empty path
            if () not in groups:
                groups[()] = []
            groups[()].append(error)

    return groups


def select_most_likely_errors(
    error_groups: dict[tuple[str | int, ...], list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], bool]:
    """Select the error group(s) most likely to be the intended model.

    Uses heuristic: the group with the fewest errors is most likely correct,
    as it requires the fewest changes to make the data valid.

    When multiple groups have the same minimum error count (a tie), returns
    all tied groups to indicate ambiguity to the user.

    Args:
        error_groups: Dictionary mapping discriminator paths to error lists

    Returns:
        Tuple of (errors_list, is_tied) where:
        - errors_list: Flattened list of errors from all tied groups
        - is_tied: True if multiple groups had the same minimum error count
    """
    if not error_groups:
        return [], False

    # Find the minimum error count
    min_error_count = min(len(errors) for errors in error_groups.values())

    # Get all groups with the minimum error count
    tied_groups = [
        errors for errors in error_groups.values() if len(errors) == min_error_count
    ]

    # Flatten all errors from tied groups
    all_errors = [error for group in tied_groups for error in group]

    # Indicate if there was a tie
    is_tied = len(tied_groups) > 1

    return all_errors, is_tied


def format_path(filtered_loc: list[str | int]) -> str:
    """Convert filtered location path to dot-separated string.

    Args:
        filtered_loc: List of path components (strings and integers)

    Returns:
        Formatted path string (e.g., "properties.name" or "items[0].value")
    """
    path_str = ""
    for i, part in enumerate(filtered_loc):
        if isinstance(part, str):
            if i > 0:
                path_str += "."
            path_str += part
        else:
            path_str += f"[{part}]"

    if not path_str:
        path_str = "(root)"

    return path_str


def format_validation_error(
    error: Any,
    console: Console,
    metadata: UnionMetadata | None = None,
    show_model_hint: bool = False,
) -> None:
    """Format and print a single validation error.

    Args:
        error: Pydantic validation error dict
        console: Rich Console instance for output
        metadata: Pre-computed UnionMetadata from introspect_union() (optional)
        show_model_hint: Show which model was selected for validation (first error only)

    TODO: Add optional Rich Table display for errors (--show-table flag)
        - Show the feature data that failed validation
        - Highlight the problematic fields
        - Makes debugging easier for lists of features

    TODO: Use error path to navigate back into original input data
        - Parse error path (e.g., [1].properties.name)
        - Navigate to that location in original input
        - Detect and drop discriminator elements (like tagged-union[...])
        - Extract exact problematic value from original input
        - Reuse this logic for Rich Table highlighting
        - Improves error messages with precise context
    """
    loc = error["loc"]

    # Determine which model was selected for this error
    selected_model = None
    if metadata is not None and show_model_hint:
        try:
            structural = create_structural_tuple(loc, metadata)

            # Look for discriminator value in the location path
            for element, struct_type in zip(loc, structural, strict=False):
                if struct_type == "discriminator" and isinstance(element, str):
                    selected_model = metadata.discriminator_to_model.get(element)
                    break
                elif struct_type == "model" and isinstance(element, str):
                    selected_model = metadata.model_name_to_model.get(element)
                    break
        except Exception:
            pass

    # Filter out union markers from the path using structural analysis
    if metadata is not None:
        try:
            structural = create_structural_tuple(loc, metadata)
            # Filter out 'union', 'model', and 'discriminator' markers
            # Keep only 'list_index' and 'field' elements for display
            filtered_loc = [
                element
                for element, struct_type in zip(loc, structural, strict=False)
                if struct_type in ("list_index", "field")
            ]
        except Exception:
            # Fall back to original loc if structural analysis fails
            filtered_loc = list(loc)
    else:
        filtered_loc = list(loc)

    # Convert to dot-separated path
    path_str = format_path(filtered_loc)

    # Show model hint if this is the first error in a group
    if selected_model is not None:
        model_name = selected_model.__name__
        console.print(f"  [dim]Probable type:[/dim] {model_name}", style="blue")
        console.print()

    # Format the error message
    msg = error["msg"]
    input_value = error.get("input")

    ctx = error.get("ctx", {})
    if "error" in ctx:
        msg = ctx["error"]
        input_value = None

    console.print(f"  {path_str}", style="cyan")
    console.print(f"    → {msg}", style="yellow")

    # Show input value if present and not too large
    if input_value is not None:
        value_str = (
            repr(input_value)
            if not isinstance(input_value, str)
            else f"'{input_value}'"
        )
        prefix = "    → Got: "
        if len(value_str) <= console.width - len(prefix):
            console.print(f"{prefix}{value_str}", style="dim")
    console.print()
