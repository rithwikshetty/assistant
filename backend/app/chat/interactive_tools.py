"""Shared interactive-tool constants and helpers.

Interactive tools pause the run and wait for user action before resuming.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


INTERACTION_TYPE_USER_INPUT = "user_input"
INTERACTIVE_TOOL_NAMES = frozenset(
    {
        "request_user_input",
    }
)

INTERACTIVE_TOOL_STEP_LABELS: Dict[str, str] = {
    "request_user_input": "Preparing input prompt",
}


def step_label_for_tool(tool_name: Any) -> str:
    key = str(tool_name or "").strip()
    if not key:
        return "Using tool"
    return INTERACTIVE_TOOL_STEP_LABELS.get(key, f"Using {key}")


def normalize_non_empty_string(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    return normalized if normalized else None


def is_interactive_tool_name(raw: Any) -> bool:
    tool_name = normalize_non_empty_string(raw)
    return bool(tool_name and tool_name in INTERACTIVE_TOOL_NAMES)


def canonicalize_interactive_request_payload(tool_name: Any, request_payload: Any) -> Dict[str, Any]:
    normalized_tool_name = normalize_non_empty_string(tool_name)
    if not normalized_tool_name or not is_interactive_tool_name(normalized_tool_name):
        return request_payload if isinstance(request_payload, dict) else {}

    canonical = dict(request_payload) if isinstance(request_payload, dict) else {}
    canonical["tool"] = normalized_tool_name
    return canonical


def is_pending_interactive_result(result: Any, *, tool_name: Any = None) -> bool:
    if not isinstance(result, dict):
        return False
    status = normalize_non_empty_string(result.get("status"))
    if status != "pending":
        return False

    interaction_type = normalize_non_empty_string(result.get("interaction_type"))
    if interaction_type == INTERACTION_TYPE_USER_INPUT:
        return True

    return is_interactive_tool_name(tool_name)
