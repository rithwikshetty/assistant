"""Conversation history formatting for the OpenAI Responses API."""

import json
from typing import Any, Dict, List, Optional

from .message_formatter import build_image_content_blocks
from ..tool_payload_sanitizer import sanitize_tool_payload_for_model


def extract_tool_executions_from_tool_calls(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build normalized tool execution blocks from tool-call payload entries."""
    if not tool_calls:
        return []

    executions: List[Dict[str, Any]] = []
    for tc in tool_calls:
        tool_name = tc.get("tool_name", "unknown")
        tool_call_id = tc.get("tool_call_id") or f"call_{tc.get('id', 'unknown')}"
        args = tc.get("args") or {}
        args_text = tc.get("args_text")
        result = tc.get("result")
        result_type = tc.get("result_type")
        is_error = tc.get("is_error", False)

        assistant_blocks = [{
            "type": "tool_use",
            "id": tool_call_id,
            "name": tool_name,
            "input": args if args else ({"query": args_text} if args_text else {}),
        }]

        result_content: List[Dict[str, Any]] = []
        if result:
            if result_type == "json":
                try:
                    parsed_result = json.loads(result)
                    parsed_result = sanitize_tool_payload_for_model(str(tool_name), parsed_result)
                    result_content = [{"type": "text", "text": json.dumps(parsed_result)}]
                except (json.JSONDecodeError, TypeError):
                    result_content = [{"type": "text", "text": str(result)}]
            else:
                result_content = [{"type": "text", "text": str(result)}]

        user_blocks = [{
            "type": "tool_result",
            "tool_use_id": tool_call_id,
            "content": result_content,
            **({"is_error": True} if is_error else {}),
        }]

        executions.append({
            "assistant_blocks": assistant_blocks,
            "user_blocks": user_blocks,
        })

    return executions


def extract_tool_executions(tool_calls: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Extract structured tool executions from normalized tool calls."""
    if not tool_calls:
        return []
    return extract_tool_executions_from_tool_calls(tool_calls)


def _render_tool_result_text(tool_name: str, raw_output: Any) -> str:
    return str(raw_output)


def _summarize_tool_executions_as_text(tool_executions: List[Dict[str, Any]]) -> str:
    """Convert structured tool executions into compact assistant context."""
    lines: List[str] = []

    for execution in tool_executions:
        if not isinstance(execution, dict):
            continue

        call_name_by_id: Dict[str, str] = {}

        for block in execution.get("assistant_blocks") or []:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "function_call":
                name = block.get("name") or "unknown_tool"
                args = block.get("arguments") or ""
                call_id = block.get("call_id")
                if isinstance(call_id, str) and call_id:
                    call_name_by_id[call_id] = str(name)
                lines.append(f"[tool call] {name} args: {args}")
            elif block_type == "tool_use":
                name = block.get("name") or "unknown_tool"
                args = block.get("input") or {}
                call_id = block.get("id")
                if isinstance(call_id, str) and call_id:
                    call_name_by_id[call_id] = str(name)
                args_str = json.dumps(args) if isinstance(args, dict) else str(args)
                lines.append(f"[tool call] {name} args: {args_str}")

        for block in execution.get("user_blocks") or []:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "function_call_output":
                call_id = block.get("call_id") or ""
                output = block.get("output") or ""
                tool_name = call_name_by_id.get(str(call_id)) or ""
                label = tool_name or call_id
                rendered_output = _render_tool_result_text(tool_name, output)
                lines.append(f"[tool result] {label}: {rendered_output}")
            elif block_type == "tool_result":
                call_id = block.get("tool_use_id") or ""
                content = block.get("content") or []
                tool_name = call_name_by_id.get(str(call_id)) or ""
                label = tool_name or call_id
                if isinstance(content, list):
                    output_parts = []
                    for c in content:
                        if isinstance(c, dict) and c.get("type") == "text":
                            output_parts.append(c.get("text", ""))
                    output = " ".join(output_parts)
                else:
                    output = str(content)
                rendered_output = _render_tool_result_text(tool_name, output)
                lines.append(f"[tool result] {label}: {rendered_output}")

    return "\n".join(lines).strip()


def format_openai_history(
    messages: List[Dict[str, Any]],
    attach_file_context: bool = True,
    file_service: Optional[Any] = None,
    db: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Format conversation history for OpenAI Responses API."""
    _ = attach_file_context
    _ = db
    formatted: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        metadata = msg.get("metadata", {}) or {}

        if role == "user":
            attachments = metadata.get("attachments", []) or []
            content_blocks: List[Dict[str, Any]] = []

            if file_service and attachments:
                try:
                    image_blocks = build_image_content_blocks(attachments, file_service)
                    content_blocks.extend(image_blocks)
                except Exception:
                    pass

            content_blocks.append({"type": "text", "text": str(content)})
            formatted.append({"role": "user", "content": content_blocks})
            continue

        if role == "assistant":
            tool_executions = extract_tool_executions(tool_calls)
            if tool_executions:
                summary_text = _summarize_tool_executions_as_text(tool_executions)
                if summary_text:
                    formatted.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": summary_text}],
                        }
                    )

                if content and str(content).strip():
                    formatted.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": str(content)}],
                        }
                    )
            else:
                formatted.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": str(content)}],
                    }
                )
            continue

        formatted.append(
            {
                "role": role,
                "content": [
                    {
                        "type": "input_text" if role == "user" else "output_text",
                        "text": str(content),
                    }
                ],
            }
        )

    return formatted


def format_history_for_provider(
    provider: str,
    messages: List[Dict[str, Any]],
    attach_file_context: bool = True,
    file_service: Optional[Any] = None,
    db: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Format conversation history for the chat provider.

    OpenAI responses share the same history format across supported models.
    """
    _ = provider
    return format_openai_history(messages, attach_file_context, file_service, db=db)
