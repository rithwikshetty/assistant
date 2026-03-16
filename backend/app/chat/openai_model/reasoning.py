"""Reasoning and response payload helpers for OpenAI Responses streams."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple


def extract_reasoning_title(text: Optional[str]) -> Optional[str]:
    """Derive a short, human-readable title from a reasoning summary."""
    if not text or not isinstance(text, str):
        return None

    working = text.strip()
    if not working:
        return None

    if working.startswith("**"):
        closing = working.find("**", 2)
        if closing != -1:
            candidate = working[2:closing].strip()
            if candidate:
                return candidate
        return None

    # No explicit markdown title. Return empty string so callers can use
    # their own default label (for example "Thinking").
    return ""


def extract_reasoning_summary_part_text(part_payload: Any) -> str:
    """Extract reasoning summary text from Responses `...summary_part.*` payloads."""
    if not isinstance(part_payload, dict):
        return ""

    part_type = str(part_payload.get("type") or "").strip().lower()
    if part_type and part_type not in {"summary_text", "text"}:
        return ""

    text = part_payload.get("text")
    return text if isinstance(text, str) else ""


def merge_reasoning_summary_text(
    *,
    existing: str,
    incoming: str,
    treat_as_snapshot: bool,
) -> Tuple[str, str]:
    """Merge incoming reasoning text into accumulated buffer.

    Returns ``(combined, delta_to_emit)``.
    """
    if not incoming:
        return existing, ""

    if treat_as_snapshot:
        if not existing:
            return incoming, incoming
        if incoming.startswith(existing):
            return incoming, incoming[len(existing) :]
        if existing.startswith(incoming):
            return existing, ""

    return existing + incoming, incoming


def extract_text_from_response_payload(response_payload: Any) -> str:
    """Best-effort extraction of assistant text from a Responses payload."""
    if not isinstance(response_payload, dict):
        return ""

    output_items = response_payload.get("output")
    if not isinstance(output_items, list):
        return ""

    chunks: List[str] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue

        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "message":
            content_blocks = item.get("content")
            if isinstance(content_blocks, list):
                for block in content_blocks:
                    if not isinstance(block, dict):
                        continue
                    block_type = str(block.get("type") or "").strip().lower()
                    if block_type not in {"output_text", "text"}:
                        continue
                    text_value = block.get("text")
                    if isinstance(text_value, str) and text_value:
                        chunks.append(text_value)
            elif isinstance(content_blocks, str) and content_blocks:
                chunks.append(content_blocks)
            continue

        if item_type in {"output_text", "text"}:
            text_value = item.get("text")
            if isinstance(text_value, str) and text_value:
                chunks.append(text_value)

    return "".join(chunks)


def extract_reasoning_replay_items(response_payload: Any) -> List[Dict[str, Any]]:
    """Extract minimal encrypted reasoning items for stateless retry continuity."""
    if not isinstance(response_payload, dict):
        return []

    output_items = response_payload.get("output")
    if not isinstance(output_items, list):
        return []

    replay_items: List[Dict[str, Any]] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "reasoning":
            continue
        encrypted_content = item.get("encrypted_content")
        if isinstance(encrypted_content, str) and encrypted_content.strip():
            summary = item.get("summary")
            summary_payload = summary if isinstance(summary, list) else []
            replay_items.append(
                {
                    "type": "reasoning",
                    "encrypted_content": encrypted_content,
                    "summary": summary_payload,
                }
            )

    return replay_items


def append_reasoning_replay_items(
    input_items: List[Dict[str, Any]],
    replay_items: List[Dict[str, Any]],
) -> None:
    """Append unique reasoning replay items into input list."""
    if not replay_items:
        return

    existing_keys: Set[Tuple[str, str]] = set()
    for item in input_items:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "reasoning":
            continue

        encrypted_content = item.get("encrypted_content")
        if not isinstance(encrypted_content, str) or not encrypted_content.strip():
            continue

        summary = item.get("summary")
        try:
            summary_key = json.dumps(summary if isinstance(summary, list) else [], sort_keys=True)
        except Exception:
            summary_key = "[]"
        existing_keys.add((encrypted_content, summary_key))

    for replay_item in replay_items:
        if not isinstance(replay_item, dict):
            continue

        encrypted_content = replay_item.get("encrypted_content")
        if not isinstance(encrypted_content, str) or not encrypted_content.strip():
            continue

        summary = replay_item.get("summary")
        try:
            summary_key = json.dumps(summary if isinstance(summary, list) else [], sort_keys=True)
        except Exception:
            summary_key = "[]"

        item_key = (encrypted_content, summary_key)
        if item_key in existing_keys:
            continue
        input_items.append(replay_item)
        existing_keys.add(item_key)
