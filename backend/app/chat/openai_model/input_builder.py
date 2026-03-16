"""Input/instructions builders for OpenAI Responses requests."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..interactive_tools import INTERACTIVE_TOOL_NAMES


# ---------------------------------------------------------------------------
# Allowlisted fields for cleaning response output items before re-sending
# as input.  Response/compact output items contain extra fields (id, status,
# phase, annotations, logprobs, created_by …) that the API rejects when
# sent back.  We keep only the fields the API accepts as input parameters.
# ---------------------------------------------------------------------------

_ALLOWED_FIELDS: Dict[str, set] = {
    "message": {"type", "role", "content"},
    "function_call": {"type", "name", "call_id", "arguments"},
    "function_call_output": {"type", "call_id", "output"},
    "reasoning": {"type", "encrypted_content", "summary"},
    "compaction": {"type", "encrypted_content"},
}

_ALLOWED_CONTENT_FIELDS: Dict[str, set] = {
    "input_text": {"type", "text"},
    "output_text": {"type", "text"},
    "input_image": {"type", "image_url", "file_id", "detail"},
    "input_file": {"type", "file_data", "file_id", "file_url", "filename"},
    "summary_text": {"type", "text"},
    "reasoning_text": {"type", "text"},
}


def _clean_content_block(block: Dict[str, Any]) -> Dict[str, Any]:
    """Clean a content/summary block using allowlisted fields."""
    block_type = block.get("type", "")
    allowed = _ALLOWED_CONTENT_FIELDS.get(block_type)
    if allowed:
        return {k: v for k, v in block.items() if k in allowed}
    # Unknown block type — strip known problematic fields
    return {k: v for k, v in block.items()
            if k not in {"status", "id", "annotations", "logprobs", "created_by"}}


def clean_output_for_input(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clean response/compact output items for re-sending as input.

    Uses an allowlist approach per item type to avoid unknown parameter errors
    when the cleaned items are sent back to the Responses API.
    """
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type", "")
        allowed = _ALLOWED_FIELDS.get(item_type)

        if allowed:
            clean: Dict[str, Any] = {}
            for k in allowed:
                if k in item:
                    v = item[k]
                    # Clean nested content/summary lists
                    if k in ("content", "summary") and isinstance(v, list):
                        clean[k] = [
                            _clean_content_block(b) if isinstance(b, dict) else b
                            for b in v
                        ]
                    else:
                        clean[k] = v
            cleaned.append(clean)
        else:
            # Unknown item type — keep everything except known-bad fields
            clean = {k: v for k, v in item.items()
                     if k not in {"status", "phase", "id", "created_by"}}
            cleaned.append(clean)

    return cleaned


def coerce_system_instructions(system_prompt: Optional[Any]) -> Optional[str]:
    """Convert dynamic system prompt blocks into plain instructions text."""
    if system_prompt is None:
        return None

    if isinstance(system_prompt, list):
        parts: List[str] = []
        for block in system_prompt:
            if isinstance(block, dict):
                txt = block.get("text")
                if isinstance(txt, str) and txt.strip():
                    parts.append(txt.strip())
        if not parts:
            return None
        return "\n\n".join(parts)

    text = str(system_prompt)
    return text.strip() or None


def convert_blocks_to_responses_content(
    blocks: List[Dict[str, Any]],
) -> Optional[List[Dict[str, Any]]]:
    """Convert internal content blocks to Responses API multi-modal content."""
    if not isinstance(blocks, list):
        return None

    parts: List[Dict[str, Any]] = []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        btype = block.get("type")

        if btype in {"input_text", "input_image", "output_text"}:
            parts.append(block)
            continue

        if btype == "text":
            txt = block.get("text")
            if isinstance(txt, str) and txt.strip():
                parts.append({"type": "input_text", "text": txt})
        elif btype == "image":
            source = block.get("source") or {}
            url: Optional[str] = None
            if isinstance(source, dict):
                url = source.get("url") or source.get("image_url")
            if isinstance(url, str) and url.strip():
                parts.append({"type": "input_image", "image_url": url})

    return parts or None


def build_input_from_history(
    conversation_history: Optional[List[Dict[str, Any]]],
    query: str | List[Dict[str, Any]],
    context_prefix: Optional[str],
) -> List[Dict[str, Any]]:
    """Build OpenAI Responses `input` list from history and current query."""
    input_items: List[Dict[str, Any]] = []

    for msg in conversation_history or []:
        role = str(msg.get("role") or "user")
        content = msg.get("content") or ""
        if isinstance(content, list):
            structured = convert_blocks_to_responses_content(content)
            if structured:
                input_items.append({"role": role, "content": structured})
                continue

            segments: List[str] = []
            for part in content:
                if isinstance(part, dict):
                    txt = part.get("text")
                    if isinstance(txt, str) and txt.strip():
                        segments.append(txt)
            text_content = "\n".join(segments) if segments else json.dumps(content)
            input_items.append({"role": role, "content": text_content})
        else:
            input_items.append({"role": role, "content": str(content)})

    if isinstance(query, list):
        has_user_query = len(query) > 0
    else:
        has_user_query = bool(str(query).strip())

    if not has_user_query:
        return input_items

    user_content: Any
    if isinstance(query, list):
        structured = convert_blocks_to_responses_content(query)
        if structured:
            user_content = structured
        else:
            segments = []
            for part in query:
                if isinstance(part, dict):
                    txt = part.get("text")
                    if isinstance(txt, str) and txt.strip():
                        segments.append(txt)
            user_content = "\n".join(segments) if segments else json.dumps(query)
    else:
        user_content = str(query)

    if context_prefix:
        if isinstance(user_content, list):
            user_content = [{"type": "input_text", "text": context_prefix}] + user_content
        else:
            user_content = f"{context_prefix}\n\n{user_content}"

    input_items.append({"role": "user", "content": user_content})
    return input_items


_SESSION_CONTEXT_PREFIX = "[Session context — summary of actions completed before context compaction]"


def _starts_with_session_context_prefix(content: Any) -> bool:
    if isinstance(content, str):
        return content.startswith(_SESSION_CONTEXT_PREFIX)

    if isinstance(content, dict):
        text = content.get("text")
        return isinstance(text, str) and text.startswith(_SESSION_CONTEXT_PREFIX)

    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.startswith(_SESSION_CONTEXT_PREFIX):
                return True

    return False


def build_pre_compaction_summary(
    input_items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build a session state summary to inject before compaction.

    Compaction preserves user messages but compresses assistant responses,
    tool calls, and tool outputs into an opaque encrypted blob.  The model
    can still "read" the blob, but loses explicit awareness of which tools
    were called and what data was retrieved.  Injecting a user-role summary
    ensures the model retains that awareness across compaction boundaries
    and avoids redundant tool calls (re-reading the same file, re-searching
    the same query, re-running the same calculation).

    Key data (numbers, costs, rates, file contents) is highlighted so the
    compaction algorithm treats it as high-value context to preserve in the
    encrypted blob.
    """
    files_read: List[str] = []
    searches: List[str] = []
    retrieval_sources: List[str] = []
    calculations: List[str] = []
    other_tools: List[str] = []

    # Map call_id → tool name for correlating outputs
    call_id_to_name: Dict[str, str] = {}
    # Collect key numeric outputs from tool results
    key_data_points: List[str] = []

    for item in input_items:
        if not isinstance(item, dict):
            continue

        item_type = item.get("type", "")

        if item_type == "function_call":
            name = item.get("name", "")
            call_id = item.get("call_id", "")
            args_str = item.get("arguments", "")
            if call_id:
                call_id_to_name[call_id] = name

            try:
                args = json.loads(args_str) if isinstance(args_str, str) and args_str.strip() else {}
            except Exception:
                args = {}

            if name == "file_read":
                file_name = args.get("name") or args.get("file_name") or ""
                file_id = args.get("file_id") or ""
                label = str(file_name or file_id).strip()
                if label:
                    files_read.append(label)
            elif name == "retrieval_web_search":
                query = args.get("query", "")
                if query:
                    searches.append(str(query)[:120])
            elif name.startswith("retrieval_"):
                query = args.get("query", "")
                source = name.replace("retrieval_", "").replace("_", " ")
                label = f"{source}: {query}" if query else source
                retrieval_sources.append(label[:120])
            elif name.startswith("calc_"):
                # Capture the calculation expression/description
                expr = args.get("expression") or args.get("description") or ""
                label = f"{name}({expr})" if expr else name
                calculations.append(label[:150])
            elif name not in INTERACTIVE_TOOL_NAMES:
                brief = name
                # Include key argument for context
                for key in ("query", "title", "action", "name"):
                    val = args.get(key)
                    if isinstance(val, str) and val.strip():
                        brief = f"{name}({key}={val[:60]})"
                        break
                other_tools.append(brief)

        elif item_type == "function_call_output":
            call_id = item.get("call_id", "")
            tool_name = call_id_to_name.get(call_id, "")
            output_str = item.get("output", "")
            if not isinstance(output_str, str):
                continue

            # Extract key numeric data from calculation results
            if tool_name.startswith("calc_") and output_str:
                # Keep calculation results — numbers are critical
                truncated = output_str[:300]
                key_data_points.append(f"{tool_name} result: {truncated}")

    if not any([files_read, searches, retrieval_sources, calculations, other_tools]):
        return None

    parts = [_SESSION_CONTEXT_PREFIX]

    if files_read:
        unique = list(dict.fromkeys(files_read))
        parts.append("Files already read: " + ", ".join(unique[:25]))

    if searches:
        unique = list(dict.fromkeys(searches))
        parts.append("Web searches completed: " + "; ".join(unique[:15]))

    if retrieval_sources:
        unique = list(dict.fromkeys(retrieval_sources))
        parts.append("Knowledge sources queried: " + "; ".join(unique[:15]))

    if calculations:
        unique = list(dict.fromkeys(calculations))
        parts.append("Calculations performed: " + "; ".join(unique[:10]))

    if key_data_points:
        parts.append("Key numeric results (retain these):")
        for dp in key_data_points[:10]:
            parts.append(f"  - {dp}")

    if other_tools:
        unique = list(dict.fromkeys(other_tools))
        parts.append("Other tools used: " + ", ".join(unique[:15]))

    parts.append("")
    parts.append(
        "The conversation context was compacted to save space. "
        "The above is everything that was done before compaction. "
        "Review this and decide: if the information gathered so far is "
        "sufficient to answer the user's question, proceed with your answer. "
        "If critical data is missing or a search returned poor results, "
        "you may re-search or use tools again — but only where genuinely needed."
    )

    summary_text = "\n".join(parts)
    return {"role": "user", "content": summary_text}


def strip_session_context_messages(
    input_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove previously-injected session context messages from input_items.

    Called before injecting a fresh summary so we don't accumulate
    multiple summaries across repeated compactions.
    """
    return [
        item for item in input_items
        if not (
            isinstance(item, dict)
            and item.get("role") == "user"
            and _starts_with_session_context_prefix(item.get("content"))
        )
    ]


def build_user_input_item(
    query: str | List[Dict[str, Any]],
    context_prefix: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Build a single user input item. Returns None if query is empty."""
    if isinstance(query, list):
        has_query = len(query) > 0
    else:
        has_query = bool(str(query).strip())
    if not has_query:
        return None

    user_content: Any
    if isinstance(query, list):
        structured = convert_blocks_to_responses_content(query)
        if structured:
            user_content = structured
        else:
            segments = []
            for part in query:
                if isinstance(part, dict):
                    txt = part.get("text")
                    if isinstance(txt, str) and txt.strip():
                        segments.append(txt)
            user_content = "\n".join(segments) if segments else json.dumps(query)
    else:
        user_content = str(query)

    if context_prefix:
        if isinstance(user_content, list):
            user_content = [{"type": "input_text", "text": context_prefix}] + user_content
        else:
            user_content = f"{context_prefix}\n\n{user_content}"

    return {"role": "user", "content": user_content}
