"""Redis-backed queued run orchestration for phase-1 local supervisors."""

from __future__ import annotations

import json
import socket
from typing import Any, Dict, Optional

from ...config.settings import settings
from ...logging import log_event
from ...services.redis_pubsub import get_async_redis

import logging

logger = logging.getLogger(__name__)

_RUN_QUEUE_STREAM = "assist:chat:run-queue"
_RUN_QUEUE_GROUP = "assist-chat-run-supervisor"
_RUN_ACTIVE_COUNTER = "assist:chat:active-runs"


def build_consumer_name() -> str:
    hostname = socket.gethostname().split(".")[0] or "host"
    return f"{hostname}-{id(logger)}"


async def ensure_run_queue_group() -> None:
    redis_client = await get_async_redis()
    try:
        await redis_client.xgroup_create(
            _RUN_QUEUE_STREAM,
            _RUN_QUEUE_GROUP,
            id="0",
            mkstream=True,
        )
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def enqueue_run_command(
    *,
    conversation_id: str,
    run_id: str,
    user_id: str,
    user_message_id: str,
    resume_assistant_message_id: Optional[str] = None,
    stream_context: Optional[Dict[str, Any]] = None,
) -> str:
    redis_client = await get_async_redis()
    payload = {
        "conversation_id": conversation_id,
        "run_id": run_id,
        "user_id": user_id,
        "user_message_id": user_message_id,
        "resume_assistant_message_id": resume_assistant_message_id or "",
    }
    if isinstance(stream_context, dict) and stream_context:
        payload["stream_context"] = stream_context
    entry_id = await redis_client.xadd(
        _RUN_QUEUE_STREAM,
        {"payload": json.dumps(payload)},
        maxlen=max(1000, int(getattr(settings, "run_supervisor_queue_max_len", 20000) or 20000)),
    )
    log_event(
        logger,
        "INFO",
        "chat.run_queue.enqueued",
        "timing",
        conversation_id=conversation_id,
        run_id=run_id,
        user_id=user_id,
        queue_entry_id=entry_id,
    )
    return str(entry_id)


async def read_next_run_command(
    *,
    consumer_name: str,
    block_ms: int,
) -> Optional[tuple[str, Dict[str, Any]]]:
    redis_client = await get_async_redis()
    rows = await redis_client.xreadgroup(
        _RUN_QUEUE_GROUP,
        consumer_name,
        {_RUN_QUEUE_STREAM: ">"},
        count=1,
        block=max(100, int(block_ms)),
    )
    if not rows:
        return None

    for _stream_name, entries in rows:
        for entry_id, entry_data in entries:
            raw_payload = entry_data.get("payload")
            if not isinstance(raw_payload, str) or not raw_payload.strip():
                return str(entry_id), {}
            try:
                parsed = json.loads(raw_payload)
            except Exception:
                parsed = {}
            return str(entry_id), parsed if isinstance(parsed, dict) else {}
    return None


async def acknowledge_run_command(entry_id: str) -> None:
    redis_client = await get_async_redis()
    await redis_client.xack(_RUN_QUEUE_STREAM, _RUN_QUEUE_GROUP, entry_id)


async def claim_global_run_capacity(limit: int) -> bool:
    redis_client = await get_async_redis()
    current = await redis_client.incr(_RUN_ACTIVE_COUNTER)
    normalized_limit = max(1, int(limit))
    if int(current) <= normalized_limit:
        return True
    await redis_client.decr(_RUN_ACTIVE_COUNTER)
    return False


async def release_global_run_capacity() -> None:
    redis_client = await get_async_redis()
    current = await redis_client.decr(_RUN_ACTIVE_COUNTER)
    if int(current) < 0:
        await redis_client.set(_RUN_ACTIVE_COUNTER, "0")
