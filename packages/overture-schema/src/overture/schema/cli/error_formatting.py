"""Error formatting and grouping for validation errors."""

from pydantic import BaseModel
from rich.console import Console

from .type_analysis import (
    UnionMetadata,
    create_structural_tuple,
    extract_discriminator_path,
    get_item_index,
    infer_model_from_error,
)
from .types import ErrorLocation, ValidationErrorDict


def group_errors_by_discriminator(
    errors: list[ValidationErrorDict],
    metadata: UnionMetadata,
) -> dict[ErrorLocation, list[ValidationErrorDict]]:
    """Group validation errors by their discriminator path.

    Errors are grouped by which model variant they're associated with, as indicated
    by their discriminator path. This allows the CLI to show only errors for the most
    likely intended type, rather than overwhelming the user with errors from all
    possible union variants.

    Args:
        errors: List of Pydantic validation error dicts
        metadata: Pre-computed UnionMetadata from introspect_union()

    Returns:
        Dictionary mapping discriminator paths to lists of errors

    Examples:
        >>> # Errors from validating two buildings with different issues
        >>> errors = [
        ...     {'loc': (0, 'tagged-union[type]', 'building', 'height'), 'msg': 'Field required'},
        ...     {'loc': (0, 'tagged-union[type]', 'building', 'id'), 'msg': 'Field required'},
        ...     {'loc': (1, 'tagged-union[type]', 'building', 'geometry'), 'msg': 'Invalid geometry'},
        ... ]
        >>> metadata = introspect_union(BuildingUnion)
        >>> groups = group_errors_by_discriminator(errors, metadata)
        >>> list(groups.keys())
        [('tagged-union[type]', 'building')]
        >>> len(groups[('tagged-union[type]', 'building')])
        3

        >>> # Errors from ambiguous data matching multiple types
        >>> errors = [
        ...     {'loc': ('tagged-union[type]', 'building', 'height'), 'msg': 'Field required'},
        ...     {'loc': ('tagged-union[type]', 'building_part', 'building_id'), 'msg': 'Field required'},
        ... ]
        >>> groups = group_errors_by_discriminator(errors, metadata)
        >>> len(groups)  # Two groups - one for each potential type
        2
        >>> ('tagged-union[type]', 'building') in groups
        True
        >>> ('tagged-union[type]', 'building_part') in groups
        True
    """
    groups: dict[ErrorLocation, list[ValidationErrorDict]] = {}

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


def analyze_collection_heterogeneity(
    errors: list[ValidationErrorDict],
    metadata: UnionMetadata,
) -> tuple[dict[int, type[BaseModel] | None], bool]:
    """Analyze a collection to detect type heterogeneity.

    Args:
        errors: List of Pydantic validation error dicts
        metadata: Pre-computed UnionMetadata from introspect_union()

    Returns:
        Tuple of (item_types, is_heterogeneous) where:
        - item_types: Dict mapping item index to inferred model type
        - is_heterogeneous: True if collection contains multiple model types
    """
    # Group errors by item index
    item_errors: dict[int | None, list[ValidationErrorDict]] = {}
    for error in errors:
        item_idx = get_item_index(error["loc"])
        if item_idx not in item_errors:
            item_errors[item_idx] = []
        item_errors[item_idx].append(error)

    # Infer the most likely type for each item
    # Use heuristic: type with FEWEST errors is most likely correct
    item_types: dict[int, type[BaseModel] | None] = {}
    for item_idx, item_error_list in item_errors.items():
        if item_idx is None:
            continue

        # Group this item's errors by inferred type
        errors_by_type: dict[type[BaseModel], list[ValidationErrorDict]] = {}
        for error in item_error_list:
            inferred_type = infer_model_from_error(error, metadata)
            if inferred_type is not None:
                if inferred_type not in errors_by_type:
                    errors_by_type[inferred_type] = []
                errors_by_type[inferred_type].append(error)

        if errors_by_type:
            # Select the type with the FEWEST errors (smallest edit distance)
            item_types[item_idx] = min(
                errors_by_type.keys(), key=lambda t: len(errors_by_type[t])
            )
        else:
            item_types[item_idx] = None

    # Check if the collection is heterogeneous
    unique_types = {t for t in item_types.values() if t is not None}
    is_heterogeneous = len(unique_types) > 1

    return item_types, is_heterogeneous


def select_most_likely_errors(
    error_groups: dict[ErrorLocation, list[ValidationErrorDict]],
    metadata: UnionMetadata | None = None,
    all_errors: list[ValidationErrorDict] | None = None,
) -> tuple[list[ValidationErrorDict], bool, bool, dict[int, type[BaseModel] | None]]:
    """Select the error group(s) most likely to be the intended model.

    Uses heuristic: the group with the fewest errors is most likely correct,
    as it requires the fewest changes to make the data valid.

    When multiple groups have the same minimum error count (a tie), returns
    all tied groups to indicate ambiguity to the user.

    For heterogeneous collections, returns ALL errors since different items
    may have different intended types.

    Args:
        error_groups: Dictionary mapping discriminator paths to error lists
        metadata: Optional UnionMetadata for heterogeneity detection
        all_errors: Optional list of all errors for heterogeneity analysis

    Returns:
        Tuple of (errors_list, is_tied, is_heterogeneous, item_types) where:
        - errors_list: List of errors to display
        - is_tied: True if multiple groups had the same minimum error count
        - is_heterogeneous: True if collection contains multiple model types
        - item_types: Dict mapping item index to inferred model type
    """
    if not error_groups:
        return [], False, False, {}

    # Check for heterogeneous collections
    is_heterogeneous = False
    _item_types: dict[int, type[BaseModel] | None] = {}
    if metadata is not None and all_errors is not None:
        _item_types, is_heterogeneous = analyze_collection_heterogeneity(
            all_errors, metadata
        )

    # For heterogeneous collections, return only errors matching each item's inferred type
    if is_heterogeneous and all_errors is not None:
        filtered_errors = []
        for error in all_errors:
            item_idx = get_item_index(error["loc"])
            if item_idx is not None and item_idx in _item_types:
                # Only include this error if it matches the inferred type for this item
                if metadata is not None:
                    error_type = infer_model_from_error(error, metadata)
                    if error_type == _item_types[item_idx]:
                        filtered_errors.append(error)
            else:
                # Non-list errors or items without inferred type - include them
                filtered_errors.append(error)

        return filtered_errors, False, True, _item_types

    # Find the minimum error count
    min_error_count = min(len(errors) for errors in error_groups.values())

    # Get all groups with the minimum error count
    tied_groups = [
        errors for errors in error_groups.values() if len(errors) == min_error_count
    ]

    # Flatten all errors from tied groups
    flattened_errors = [error for group in tied_groups for error in group]

    # Indicate if there was a tie
    is_tied = len(tied_groups) > 1

    return flattened_errors, is_tied, is_heterogeneous, _item_types


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
    error: ValidationErrorDict,
    console: Console,
    metadata: UnionMetadata | None = None,
    show_model_hint: bool = False,
    item_type: type[BaseModel] | None = None,
    show_item_type: bool = False,
) -> None:
    """Format and print a single validation error.

    Args:
        error: Pydantic validation error dict
        console: Rich Console instance for output
        metadata: Pre-computed UnionMetadata from introspect_union() (optional)
        show_model_hint: Show which model was selected for validation (first error only)
        item_type: The inferred type for this item (always provided if available)
        show_item_type: Whether to display the item type in the path (True for heterogeneous collections)

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

    # Add item type annotation if requested (for heterogeneous collections)
    if show_item_type and item_type is not None:
        path_str = f"{path_str} [dim]({item_type.__name__})[/dim]"

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
