"""Chart and visualization tools for data display."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional


class ChartError(ValueError):
    """Raised when chart arguments are invalid."""


def _validate_chart_type(chart_type: Any) -> str:
    """Validate and normalize chart type."""
    if not isinstance(chart_type, str):
        raise ChartError("'type' must be a string")

    chart_type = chart_type.strip().lower()
    valid_types = {"bar", "line", "pie", "area", "stacked_bar", "waterfall"}

    if chart_type not in valid_types:
        raise ChartError(
            f"'type' must be one of {valid_types}, got '{chart_type}'"
        )

    return chart_type


def _validate_title(title: Any) -> str:
    """Validate chart title."""
    if not isinstance(title, str):
        raise ChartError("'title' must be a string")

    title = title.strip()
    if not title:
        raise ChartError("'title' cannot be empty")

    return title


def _validate_data(data: Any) -> List[Dict[str, Any]]:
    """Validate chart data array."""
    if data is None:
        raise ChartError(
            "'data' is required and must be an array of objects, e.g. "
            "[{\"name\": \"Category A\", \"value\": 42}]"
        )

    if not isinstance(data, list):
        raise ChartError(f"'data' must be an array, got {type(data).__name__}")

    if len(data) == 0:
        raise ChartError("'data' cannot be empty")

    # Validate each data point is an object
    for i, point in enumerate(data):
        if not isinstance(point, dict):
            raise ChartError(f"data[{i}] must be an object")

    return data


def _validate_optional_string(value: Any, field_name: str) -> Optional[str]:
    """Validate optional string field."""
    if value is None:
        return None

    if not isinstance(value, str):
        raise ChartError(f"'{field_name}' must be a string")

    return value.strip()


def _validate_optional_array(value: Any, field_name: str) -> Optional[List[str]]:
    """Validate optional array field."""
    if value is None:
        return None

    if not isinstance(value, list):
        raise ChartError(f"'{field_name}' must be an array")

    result = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise ChartError(f"'{field_name}[{i}]' must be a string")
        result.append(item.strip())

    return result


def _infer_data_keys(
    data: List[Dict[str, Any]],
    x_axis_key: str,
    chart_type: str,
) -> List[str]:
    """Infer which keys to use for chart values."""
    if not data:
        return []

    # Get all numeric keys from first data point
    first_point = data[0]
    numeric_keys = []

    for key, value in first_point.items():
        # Skip x-axis key
        if key == x_axis_key:
            continue

        # Check if value is numeric
        if isinstance(value, (int, float)):
            numeric_keys.append(key)

    # For pie charts, prefer 'value' if available
    if chart_type == "pie" and "value" in numeric_keys:
        return ["value"]

    # Return all numeric keys found
    return numeric_keys if numeric_keys else ["value"]


def _validate_data_sanity(
    data: List[Dict[str, Any]],
    data_keys: List[str],
    y_axis_label: Optional[str],
    chart_type: str,
) -> None:
    """
    Validate data for common errors before rendering.

    Catches:
    - Unit/scale mismatches (percentages with values >200)
    - Sparse data (most categories missing values)
    - Inconsistent keys across data points

    Raises:
        ChartError: If validation fails with actionable error message
    """
    if not data or not data_keys:
        return

    # Check 1: Unit/scale validation for percentages
    if y_axis_label and ("%" in y_axis_label or "percent" in y_axis_label.lower()):
        # Collect all numeric values
        all_values = []
        for point in data:
            for key in data_keys:
                value = point.get(key)
                if isinstance(value, (int, float)):
                    all_values.append(abs(value))

        if all_values:
            max_value = max(all_values)
            # If any percentage value is >200, it's likely a unit error
            if max_value > 200:
                raise ChartError(
                    f"Y-axis label indicates percentages ('{y_axis_label}') but data contains values up to {max_value:.0f}. "
                    f"Percentages should typically be in 0-100 range (or -100 to +100 for changes). "
                    f"If showing absolute values like £{max_value:.0f}, use a currency label like 'Cost (£)' instead of percentage. "
                    f"If showing basis points, divide by 100 to convert to percentages."
                )

    # Check 2: Data completeness - warn if >60% of categories have no data
    if len(data) >= 3:  # Only check for 3+ categories
        points_with_data = 0
        for point in data:
            has_value = False
            for key in data_keys:
                value = point.get(key)
                if isinstance(value, (int, float)) and value != 0:
                    has_value = True
                    break
            if has_value:
                points_with_data += 1

        data_completeness = points_with_data / len(data)
        if data_completeness < 0.4:  # Less than 40% have data
            raise ChartError(
                f"Sparse data: Only {points_with_data} out of {len(data)} categories have values. "
                f"Charts work best when all categories have data. Consider filtering to only categories with values, "
                f"or ensure you're aggregating data correctly before creating the chart."
            )

    # Check 3: Key consistency - ensure all data points have the required keys
    for i, point in enumerate(data):
        missing_keys = [key for key in data_keys if key not in point]
        if missing_keys:
            raise ChartError(
                f"Data point {i} is missing keys: {missing_keys}. "
                f"All data points must have the same keys. "
                f"Ensure consistent data structure across all categories."
            )


def execute_create_chart(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Create a chart visualization.

    Args:
        arguments: Chart configuration with type, title, data, and optional config

    Returns:
        Chart specification for frontend rendering

    Raises:
        ChartError: If arguments are invalid
    """
    # Validate required fields
    chart_type = _validate_chart_type(arguments.get("type"))
    title = _validate_title(arguments.get("title"))
    data = _validate_data(arguments.get("data"))

    # Validate optional fields
    x_axis_key = _validate_optional_string(
        arguments.get("x_axis_key"), "x_axis_key"
    ) or "name"

    data_keys = _validate_optional_array(arguments.get("data_keys"), "data_keys")

    # If data_keys not provided, infer from data
    if not data_keys:
        data_keys = _infer_data_keys(data, x_axis_key, chart_type)

        if not data_keys:
            raise ChartError(
                f"Could not infer data keys from data. Please provide 'data_keys' parameter."
            )

    x_axis_label = _validate_optional_string(
        arguments.get("x_axis_label"), "x_axis_label"
    )
    y_axis_label = _validate_optional_string(
        arguments.get("y_axis_label"), "y_axis_label"
    )
    colors = _validate_optional_array(arguments.get("colors"), "colors")

    # Validate data points have the required keys
    for i, point in enumerate(data):
        if x_axis_key not in point:
            raise ChartError(
                f"data[{i}] missing required key '{x_axis_key}' for x-axis"
            )

        # Check at least one data key exists
        has_value = False
        for key in data_keys:
            if key in point and isinstance(point[key], (int, float)):
                has_value = True
                break

        if not has_value:
            raise ChartError(
                f"data[{i}] must have at least one numeric value from {data_keys}"
            )

    # Validate data sanity (unit/scale mismatches, sparse data, etc.)
    _validate_data_sanity(data, data_keys, y_axis_label, chart_type)

    # Build response
    return {
        "type": chart_type,
        "title": title,
        "data": data,
        "config": {
            "x_axis_key": x_axis_key,
            "data_keys": data_keys,
            "x_axis_label": x_axis_label,
            "y_axis_label": y_axis_label,
            "colors": colors,
        },
    }


# ---------------------------------------------------------------------------
# Gantt charts
# ---------------------------------------------------------------------------

class GanttError(ValueError):
    """Raised when Gantt arguments are invalid."""


def _is_date_like(value: Any) -> bool:
    """Shallow date validation: accept YYYY-MM-DD or any non-empty ISO string.

    We avoid strict parsing here to keep providers flexible; the frontend can
    normalise to exact formats for the renderer.
    """
    if not isinstance(value, str):
        return False
    val = value.strip()
    if not val:
        return False
    # Fast-path check for YYYY-MM-DD
    if len(val) >= 10 and val[4] == "-" and val[7] == "-":
        return True
    # Otherwise accept any non-empty string
    return True


def execute_create_gantt(arguments: Mapping[str, Any]) -> Dict[str, Any]:
    """Create a Gantt chart specification for frontend rendering.

    The payload mirrors the neutral, in-house renderer: tasks with start/end
    dates (yyyy-mm-dd), optional progress (0-100) and dependencies, plus a view
    hint and read-only flag.
    """
    title = arguments.get("title")
    if not isinstance(title, str) or not title.strip():
        raise GanttError("'title' must be a non-empty string")
    title = title.strip()

    tasks = arguments.get("tasks")
    if not isinstance(tasks, list) or len(tasks) == 0:
        raise GanttError("'tasks' must be a non-empty array")

    normalized: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise GanttError(f"tasks[{i}] must be an object")
        tid = task.get("id")
        name = task.get("name")
        start = task.get("start")
        end = task.get("end")
        if not isinstance(tid, str) or not tid.strip():
            raise GanttError(f"tasks[{i}].id must be a non-empty string")
        if tid in seen_ids:
            raise GanttError(f"Duplicate task id: '{tid}'")
        seen_ids.add(tid)
        if not isinstance(name, str) or not name.strip():
            raise GanttError(f"tasks[{i}].name must be a non-empty string")
        if not _is_date_like(start):
            raise GanttError(f"tasks[{i}].start must be a date string (YYYY-MM-DD or ISO)")
        if not _is_date_like(end):
            raise GanttError(f"tasks[{i}].end must be a date string (YYYY-MM-DD or ISO)")

        progress = task.get("progress")
        if progress is not None:
            try:
                progress = float(progress)
            except (TypeError, ValueError) as exc:
                raise GanttError(f"tasks[{i}].progress must be a number") from exc
            if progress < 0 or progress > 100:
                raise GanttError(f"tasks[{i}].progress must be between 0 and 100")

        dependencies = task.get("dependencies")
        if dependencies is not None and not isinstance(dependencies, str):
            raise GanttError(f"tasks[{i}].dependencies must be a string of comma-separated ids if provided")

        custom_bar_color = task.get("custom_bar_color")
        if custom_bar_color is not None and not isinstance(custom_bar_color, str):
            raise GanttError(f"tasks[{i}].custom_bar_color must be a string (hex color code)")

        normalized.append(
            {
                "id": tid.strip(),
                "name": name.strip(),
                "start": str(start).strip(),
                "end": str(end).strip(),
                **({"progress": progress} if progress is not None else {}),
                **({"dependencies": dependencies.strip()} if isinstance(dependencies, str) and dependencies.strip() else {}),
                **({"custom_bar_color": custom_bar_color.strip()} if isinstance(custom_bar_color, str) and custom_bar_color.strip() else {}),
            }
        )

    view_mode = arguments.get("view_mode", "Month")
    if not isinstance(view_mode, str) or view_mode not in {"Day", "Week", "Month", "Year"}:
        raise GanttError("'view_mode' must be one of 'Day', 'Week', 'Month', 'Year'")

    readonly = bool(arguments.get("readonly", False))

    return {
        "title": title,
        "tasks": normalized,
        "view_mode": view_mode,
        "readonly": readonly,
    }
