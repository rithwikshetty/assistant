"""Redis-backed cache for OpenAI stateless input item snapshots."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ...config.settings import settings
from ...logging import log_event
from ...services.redis_pubsub import get_async_redis


logger = logging.getLogger(__name__)

_INPUT_ITEMS_CACHE_PREFIX = "chat:input_items"


def _cache_key(conversation_id: str) -> str:
    return f"{_INPUT_ITEMS_CACHE_PREFIX}:{conversation_id}"


def _cache_ttl_seconds() -> int:
    # Reuse the active stream TTL so snapshot continuity survives page refreshes
    # and short reconnect windows while still expiring naturally.
    return max(60, int(getattr(settings, "redis_stream_initial_ttl", 43200) or 43200))


async def get_cached_input_items(conversation_id: str) -> Optional[List[Dict[str, Any]]]:
    """Return cached input items for a conversation, or None when missing."""
    key = _cache_key(conversation_id)
    try:
        redis_client = await get_async_redis()
        raw_payload = await redis_client.get(key)
        if not isinstance(raw_payload, str) or not raw_payload.strip():
            return None
        decoded = json.loads(raw_payload)
        if isinstance(decoded, list):
            return [item for item in decoded if isinstance(item, dict)]
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.input_items_cache.read_failed",
            "retry",
            conversation_id=conversation_id,
            exc_info=True,
        )
    return None


async def set_cached_input_items(
    conversation_id: str,
    input_items: List[Dict[str, Any]],
) -> None:
    """Cache input items for follow-up turn continuity."""
    if not isinstance(input_items, list) or not input_items:
        return

    payload = [item for item in input_items if isinstance(item, dict)]
    if not payload:
        return

    key = _cache_key(conversation_id)
    ttl = _cache_ttl_seconds()
    try:
        serialized = json.dumps(payload, separators=(",", ":"))
        redis_client = await get_async_redis()
        await redis_client.set(key, serialized, ex=ttl)
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.input_items_cache.write_failed",
            "retry",
            conversation_id=conversation_id,
            item_count=len(payload),
            ttl_seconds=ttl,
            exc_info=True,
        )


__all__ = ["get_cached_input_items", "set_cached_input_items"]

