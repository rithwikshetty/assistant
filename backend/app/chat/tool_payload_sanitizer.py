from __future__ import annotations

from typing import Any, Dict

_DROP = object()
_BASE64_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r")
_MODEL_MAX_TEXT_CHARS = 4_096


def _truncate_text(value: str, max_chars: int) -> str:
    text = value.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _looks_like_base64_blob(value: str) -> bool:
    """Heuristic to detect large base64-like strings without key allowlists."""
    if len(value) < 2_048:
        return False
    sample = value[:8_192]
    if not sample:
        return False
    valid_count = sum(1 for ch in sample if ch in _BASE64_CHARS)
    return (valid_count / len(sample)) >= 0.98


def _prune_image_value(value: Any, *, for_model: bool) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, inner in value.items():
            pruned = _prune_image_value(inner, for_model=for_model)
            if pruned is _DROP:
                continue
            out[key] = pruned
        return out

    if isinstance(value, list):
        out = []
        for inner in value:
            pruned = _prune_image_value(inner, for_model=for_model)
            if pruned is _DROP:
                continue
            out.append(pruned)
        return out

    if isinstance(value, str):
        text = value.strip()
        if _looks_like_base64_blob(text):
            return _DROP
        # Extra guard for model replay: avoid unexpectedly large text fields.
        if for_model and len(text) > _MODEL_MAX_TEXT_CHARS:
            return _DROP
        return text

    return value


def _prune_file_read_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop inline image bytes from file_read payloads while keeping text context."""
    content_blocks = payload.get("_content_blocks")
    if not isinstance(content_blocks, list):
        return payload

    has_image_blocks = False
    normalized_blocks: list[Dict[str, Any]] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue

        block_type = str(block.get("type") or "").strip().lower()
        if block_type != "image":
            normalized_blocks.append(block)
            continue

        has_image_blocks = True
        source = block.get("source") if isinstance(block.get("source"), dict) else {}
        media_type = source.get("media_type") if isinstance(source, dict) else None
        placeholder: Dict[str, Any] = {
            "type": "image_omitted",
            "text": "Image bytes omitted from model context to control token usage.",
        }
        if isinstance(media_type, str) and media_type.strip():
            placeholder["media_type"] = media_type.strip()
        normalized_blocks.append(placeholder)

    if not has_image_blocks:
        return payload

    pruned = dict(payload)
    pruned["_content_blocks"] = normalized_blocks
    if "image_context_note" not in pruned:
        pruned["image_context_note"] = "Image bytes were omitted from the replay context."
    return pruned


def sanitize_tool_payload_for_model(name: str, payload: Any) -> Any:
    """Prepare tool payload for model input (context-safe)."""
    if not isinstance(payload, dict):
        return payload

    tool_name = (name or "").strip()
    if tool_name == "file_read":
        return _prune_file_read_payload(payload)

    return payload


def sanitize_tool_payload_for_storage(name: str, payload: Any) -> Any:
    """Prepare tool payload for DB persistence / resume reconstruction."""
    if not isinstance(payload, dict):
        return payload

    tool_name = (name or "").strip()
    if tool_name == "file_read":
        return _prune_file_read_payload(payload)

    return payload
