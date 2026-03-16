"""Helpers for OpenAI Responses tool-loop execution.

This module keeps tool-loop argument parsing, parallel execution, and
input-item reconstruction isolated from the main streaming transport logic.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from ..tool_loop_utils import build_await_user_input_event, partition_tool_results_openai
from ..tool_payload_sanitizer import sanitize_tool_payload_for_model


@dataclass
class OpenAIToolLoopTurnOutcome:
    """Result of executing one OpenAI function-call batch."""

    emitted_events: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    next_items: List[Dict[str, Any]]
    tool_execution_structure: Optional[Dict[str, Any]]
    await_user_input_event: Optional[Dict[str, Any]]


async def execute_openai_tool_loop_turn(
    *,
    tool_calls: List[Dict[str, Any]],
    tool_context: Dict[str, Any],
    execute_tool_fn: Callable[..., Awaitable[Dict[str, Any]]],
) -> OpenAIToolLoopTurnOutcome:
    """Execute OpenAI function calls and prepare next-loop input items."""
    emitted_events: List[Dict[str, Any]] = []
    tool_results: List[Dict[str, Any]] = []
    pending_tasks: List[asyncio.Task[Tuple[str, str, Dict[str, Any]]]] = []
    primary_call_id_by_signature: Dict[str, str] = {}
    duplicate_calls_by_primary: Dict[str, List[Tuple[str, str]]] = {}

    for call in tool_calls:
        name = str(call.get("name") or "")
        call_id = str(call.get("call_id") or call.get("id") or name or "tool_call")

        parse_error, args = _parse_tool_arguments(call.get("arguments"))
        if parse_error:
            error_payload = {"message": parse_error}
            emitted_events.append(
                {
                    "type": "tool_error",
                    "name": name,
                    "call_id": call_id,
                    "item_id": call_id,
                    "content": error_payload,
                }
            )
            tool_results.append(
                {"call_id": call_id, "name": name, "status": "error", "error": error_payload}
            )
            continue

        emitted_events.append(
            {
                "type": "tool_arguments",
                "name": name,
                "call_id": call_id,
                "item_id": call_id,
                "content": args,
            }
        )

        if "query" in args:
            emitted_events.append(
                {
                    "type": "tool_query",
                    "name": name,
                    "call_id": call_id,
                    "item_id": call_id,
                    "content": args.get("query"),
                }
            )

        signature = _tool_call_signature(name=name, args=args)
        primary_call_id = primary_call_id_by_signature.get(signature)
        if primary_call_id:
            duplicate_calls_by_primary.setdefault(primary_call_id, []).append((call_id, name))
            continue

        primary_call_id_by_signature[signature] = call_id
        pending_tasks.append(
            asyncio.create_task(
                _run_tool(
                    execute_tool_fn=execute_tool_fn,
                    tool_name=name,
                    tool_args=args,
                    tool_call_id=call_id,
                    tool_context=tool_context,
                )
            )
        )

    for future in asyncio.as_completed(pending_tasks):
        call_id, name, outcome = await future
        duplicate_calls = duplicate_calls_by_primary.get(call_id, [])
        if outcome.get("status") == "ok":
            result_payload = outcome.get("result")
            emitted_events.append(
                {
                    "type": "tool_result",
                    "name": name,
                    "call_id": call_id,
                    "item_id": call_id,
                    "content": result_payload,
                }
            )
            tool_results.append(
                {
                    "call_id": call_id,
                    "name": name,
                    "status": "ok",
                    "result": result_payload,
                }
            )

            # Fan out identical-call result to duplicate call_ids. Keep pending
            # user-input requests singular to avoid duplicate prompt events.
            if isinstance(result_payload, dict) and result_payload.get("status") == "pending":
                continue

            for duplicate_call_id, duplicate_name in duplicate_calls:
                emitted_events.append(
                    {
                        "type": "tool_result",
                        "name": duplicate_name,
                        "call_id": duplicate_call_id,
                        "item_id": duplicate_call_id,
                        "content": result_payload,
                        "deduped_from_call_id": call_id,
                    }
                )
                tool_results.append(
                    {
                        "call_id": duplicate_call_id,
                        "name": duplicate_name,
                        "status": "ok",
                        "result": result_payload,
                    }
                )
            continue

        error_payload = outcome.get("error") if isinstance(outcome.get("error"), dict) else {"message": "Unknown error"}
        emitted_events.append(
            {
                "type": "tool_error",
                "name": name,
                "call_id": call_id,
                "item_id": call_id,
                "content": error_payload,
            }
        )
        tool_results.append(
            {
                "call_id": call_id,
                "name": name,
                "status": "error",
                "error": error_payload,
            }
        )
        for duplicate_call_id, duplicate_name in duplicate_calls:
            emitted_events.append(
                {
                    "type": "tool_error",
                    "name": duplicate_name,
                    "call_id": duplicate_call_id,
                    "item_id": duplicate_call_id,
                    "content": error_payload,
                    "deduped_from_call_id": call_id,
                }
            )
            tool_results.append(
                {
                    "call_id": duplicate_call_id,
                    "name": duplicate_name,
                    "status": "error",
                    "error": error_payload,
                }
            )

    completed_results, pending_input = partition_tool_results_openai(tool_results)
    if pending_input:
        await_user_input_event = build_await_user_input_event(
            [
                {
                    "call_id": outcome.get("call_id"),
                    "name": outcome.get("name"),
                    "result": outcome.get("result"),
                }
                for outcome in pending_input
            ]
        )
        return OpenAIToolLoopTurnOutcome(
            emitted_events=emitted_events,
            tool_results=tool_results,
            next_items=[],
            tool_execution_structure=None,
            await_user_input_event=await_user_input_event,
        )

    next_items = _build_next_items(tool_calls=tool_calls, completed_results=completed_results)
    tool_execution_structure = _build_tool_execution_structure(tool_calls=tool_calls, tool_results=tool_results)

    return OpenAIToolLoopTurnOutcome(
        emitted_events=emitted_events,
        tool_results=tool_results,
        next_items=next_items,
        tool_execution_structure=tool_execution_structure,
        await_user_input_event=None,
    )


def _parse_tool_arguments(raw_arguments: Any) -> Tuple[Optional[str], Dict[str, Any]]:
    """Parse OpenAI function-call arguments into a dict."""
    try:
        if isinstance(raw_arguments, str):
            parsed = json.loads(raw_arguments) if raw_arguments.strip() else {}
        elif isinstance(raw_arguments, dict):
            parsed = raw_arguments
        else:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        return None, parsed
    except Exception as exc:
        return f"Invalid tool arguments: {exc}", {}


def _tool_call_signature(*, name: str, args: Dict[str, Any]) -> str:
    """Stable signature for deduping identical tool invocations in one turn."""
    try:
        normalized_args = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        normalized_args = str(args)
    return f"{name}|{normalized_args}"


async def _run_tool(
    *,
    execute_tool_fn: Callable[..., Awaitable[Dict[str, Any]]],
    tool_name: str,
    tool_args: Dict[str, Any],
    tool_call_id: str,
    tool_context: Dict[str, Any],
) -> Tuple[str, str, Dict[str, Any]]:
    try:
        result = await execute_tool_fn(name=tool_name, arguments=tool_args, context=tool_context)
        return tool_call_id, tool_name, {"status": "ok", "result": result}
    except Exception as exc:
        if tool_name == "viz_create_chart":
            error_message = str(exc)
            if "Sparse data:" in error_message:
                retry_spec = _build_sparse_chart_retry_args(tool_args)
                if retry_spec is not None:
                    retry_args, original_points, filtered_points = retry_spec
                    try:
                        retry_result = await execute_tool_fn(
                            name=tool_name,
                            arguments=retry_args,
                            context=tool_context,
                        )
                        if isinstance(retry_result, dict):
                            retry_result = dict(retry_result)
                            retry_result["auto_retry"] = {
                                "attempted": True,
                                "reason": "sparse_data",
                                "original_points": original_points,
                                "filtered_points": filtered_points,
                            }
                        return tool_call_id, tool_name, {"status": "ok", "result": retry_result}
                    except Exception:
                        pass
        return tool_call_id, tool_name, {"status": "error", "error": {"message": str(exc)}}


def _build_next_items(
    *,
    tool_calls: List[Dict[str, Any]],
    completed_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build OpenAI function_call + function_call_output items for next turn."""
    next_items: List[Dict[str, Any]] = []

    for call in tool_calls:
        call_id = str(call.get("call_id") or call.get("id") or "").strip()
        if not call_id:
            continue
        next_items.append(
            {
                "type": "function_call",
                "name": str(call.get("name") or ""),
                "call_id": call_id,
                "arguments": str(call.get("arguments") or ""),
            }
        )

    for outcome in completed_results:
        call_id = outcome.get("call_id")
        if not call_id:
            continue

        payload = _build_model_tool_output_payload(outcome)

        next_items.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": _safe_json_dumps(payload),
            }
        )

    return next_items


def _build_tool_execution_structure(
    *,
    tool_calls: List[Dict[str, Any]],
    tool_results: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build structured tool execution payload for history reconstruction."""
    assistant_blocks: List[Dict[str, Any]] = []
    for call in tool_calls:
        assistant_blocks.append(
            {
                "type": "function_call",
                "name": call.get("name") or "",
                "call_id": call.get("call_id") or call.get("id") or "",
                "arguments": call.get("arguments") or "",
            }
        )

    user_blocks: List[Dict[str, Any]] = []
    for outcome in tool_results:
        call_id = outcome.get("call_id") or ""
        payload = _build_model_tool_output_payload(outcome)
        user_blocks.append(
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": _safe_json_dumps(payload),
            }
        )

    if not assistant_blocks and not user_blocks:
        return None

    return {
        "type": "tool_execution_structure",
        "assistant_blocks": assistant_blocks,
        "user_blocks": user_blocks,
    }


def _safe_json_dumps(payload: Any) -> str:
    try:
        return json.dumps(payload)
    except Exception:
        return json.dumps({"error": "Failed to serialize tool result"})


def _is_nonzero_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return float(value) != 0.0


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _derive_chart_data_keys(args: Dict[str, Any]) -> List[str]:
    raw_data_keys = args.get("data_keys")
    if isinstance(raw_data_keys, list):
        normalized = [
            item.strip()
            for item in raw_data_keys
            if isinstance(item, str) and item.strip()
        ]
        if normalized:
            return normalized

    data = args.get("data")
    if not isinstance(data, list) or not data:
        return []

    x_axis_key = args.get("x_axis_key")
    x_axis_key = x_axis_key.strip() if isinstance(x_axis_key, str) and x_axis_key.strip() else "name"
    discovered: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if key == x_axis_key:
                continue
            if _is_number(value):
                discovered.add(key)
    return list(discovered)


def _build_sparse_chart_retry_args(tool_args: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], int, int]]:
    data = tool_args.get("data")
    if not isinstance(data, list) or len(data) < 3:
        return None

    data_keys = _derive_chart_data_keys(tool_args)
    if not data_keys:
        return None

    filtered_data: List[Dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        if any(_is_nonzero_number(row.get(key)) for key in data_keys):
            filtered_data.append(dict(row))

    if not filtered_data or len(filtered_data) >= len(data):
        return None

    retry_args = dict(tool_args)
    retry_args["data"] = filtered_data
    return retry_args, len(data), len(filtered_data)


def _build_model_tool_output_payload(outcome: Dict[str, Any]) -> Any:
    raw_payload = outcome.get("result") if outcome.get("status") == "ok" else outcome.get("error") or {}
    payload = sanitize_tool_payload_for_model(str(outcome.get("name") or ""), raw_payload)
    if outcome.get("status") == "error":
        return {"status": "error", "error": payload}
    return payload
