"""Shared utilities for the provider tool loop.

Extracted from duplicated streaming logic to keep
user-input pause handling in one place.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .interactive_tools import is_pending_interactive_result

def partition_tool_results_openai(
    tool_results: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split tool results into completed and pending-input.

    Returns (completed, pending_user_input) where each item has the same
    shape as the input dicts ({call_id, name, status, result/error}).
    """
    completed: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for outcome in tool_results:
        raw = outcome.get("result") if outcome.get("status") == "ok" else None
        if outcome.get("status") == "ok" and is_pending_interactive_result(raw, tool_name=outcome.get("name")):
            pending.append(outcome)
        else:
            completed.append(outcome)
    return completed, pending


def build_await_user_input_event(
    pending_calls: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the ``await_user_input`` stream event from pending tool calls.

    *pending_calls* should be a list of dicts each having at minimum
    ``call_id``, ``name``, and ``result`` (the raw tool output).
    """
    pending_requests: List[Dict[str, Any]] = []
    for call in pending_calls:
        result_payload = call.get("result")
        if isinstance(result_payload, dict):
            pending_requests.append({
                "call_id": call.get("call_id"),
                "tool_name": call.get("name"),
                "request": result_payload.get("request"),
                "result": result_payload,
            })
    return {
        "type": "await_user_input",
        "content": {"pending_requests": pending_requests},
    }
