"""
Redis Streams-backed chat event streaming.

Events are published to Redis Streams (XADD) and consumed via XREAD BLOCK,
enabling any worker/instance to serve any SSE endpoint. Stream metadata
(status, user_id, etc.) lives in a Redis Hash. Cancellation uses a
short-lived Redis key. User lifecycle events (stream_started/completed/failed)
are broadcast via Redis Pub/Sub with per-worker local fan-out.

The producing worker still holds a local ChatStream dataclass for its
asyncio.Task reference.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Any, AsyncGenerator, Dict, List, Optional
from uuid import uuid4

import redis

from ..config.settings import settings
from ..chat.ws_contract import validate_chat_user_event_payload
from ..logging import log_event
from .redis_pubsub import get_async_redis

logger = logging.getLogger(__name__)

# Redis key prefixes
_EVENTS_KEY = "assist:stream:events:{conv_id}"
_META_KEY = "assist:stream:meta:{conv_id}"
_EVENT_ID_INDEX_KEY = "assist:stream:event-id-index:{conv_id}"
_CANCEL_KEY = "assist:stream:cancel:{conv_id}"
_USER_STREAMS_KEY = "assist:user:streams:{user_id}"
_USER_EVENTS_CHANNEL = "assist:user:events:{user_id}"
_CONVERSATION_REGISTER_CHANNEL = "assist:stream:registered:{conv_id}"
_REGISTER_LOCK_KEY = "assist:stream:register-lock:{conv_id}"

# Worker identifier for debugging
_WORKER_ID = f"{os.getpid()}-{id(asyncio)}"

# Initial TTL for stream keys while active
_STREAM_INITIAL_TTL = max(60, int(getattr(settings, "redis_stream_initial_ttl", 43200) or 43200))
# TTL for per-user active stream set
_USER_STREAMS_TTL = max(60, int(getattr(settings, "redis_stream_user_set_ttl", _STREAM_INITIAL_TTL) or _STREAM_INITIAL_TTL))
# Cancel key TTL
_CANCEL_TTL = 120
_REGISTER_LOCK_TTL = 15
_ACTIVE_STREAM_STATUSES = {"running", "resumed"}
_STREAM_ENTRY_ID_RE = re.compile(r"^\d+-\d+$")


class StreamRegistrationConflictError(RuntimeError):
    """Raised when a stream registration overlaps with an active registration/run."""


_RELEASE_REGISTER_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


# ── StreamContext (unchanged) ─────────────────────────────────────────────

@dataclass
class StreamContext:
    """Pre-loaded data from the submit handler, passed to the background task."""
    user_content: str
    attachments_meta: List[Dict[str, Any]]
    is_admin: bool
    is_new_conversation: bool
    prefetched_context: Optional[Dict[str, Any]] = None


# ── ChatStream (local dataclass on producing worker) ─────────────────────

# Throttle TTL refreshes — no need to EXPIRE on every event when TTL is 12h.
_TTL_REFRESH_INTERVAL = 30.0  # seconds


@dataclass
class ChatStream:
    """Local representation of a running stream on the producing worker.

    publish(), check_cancel(), update_step(), and set_status() are async
    and operate on Redis.
    """
    conversation_id: str
    user_id: str
    user_message_id: str
    run_id: Optional[str]
    task: asyncio.Task
    status: str = "running"
    current_step: Optional[str] = None
    context: Optional[StreamContext] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _last_ttl_refresh: float = field(default=0.0, init=False, repr=False)

    def _should_refresh_ttl(self) -> bool:
        now = monotonic()
        if now - self._last_ttl_refresh >= _TTL_REFRESH_INTERVAL:
            self._last_ttl_refresh = now
            return True
        return False

    async def publish(self, event: Dict[str, Any]) -> None:
        """XADD event to Redis Stream.

        XADD must be standalone (we need the returned stream entry ID for
        indexing). The follow-up index + TTL work is batched into a single
        conditional pipeline, and TTL refreshes are throttled to once per
        _TTL_REFRESH_INTERVAL seconds instead of every event.
        """
        r = await get_async_redis()
        events_key = _EVENTS_KEY.format(conv_id=self.conversation_id)
        event = self._normalize_event_for_storage(event)
        event_json = json.dumps(event, default=str)

        stream_entry_id = await r.xadd(
            events_key,
            {"data": event_json},
            maxlen=settings.redis_stream_max_len,
        )

        event_id = event.get("id")
        should_index = isinstance(event_id, int) and event_id >= 0
        refresh_ttl = self._should_refresh_ttl()

        if should_index or refresh_ttl:
            meta_key = _META_KEY.format(conv_id=self.conversation_id)
            index_key = _EVENT_ID_INDEX_KEY.format(conv_id=self.conversation_id)
            pipe = r.pipeline()
            if should_index:
                pipe.hset(index_key, str(event_id), stream_entry_id)
                pipe.hset(meta_key, "last_stream_event_id", str(event_id))
            if refresh_ttl:
                user_streams_key = _USER_STREAMS_KEY.format(user_id=self.user_id)
                pipe.expire(events_key, _STREAM_INITIAL_TTL)
                pipe.expire(meta_key, _STREAM_INITIAL_TTL)
                pipe.expire(index_key, _STREAM_INITIAL_TTL)
                pipe.expire(user_streams_key, _USER_STREAMS_TTL)
            await pipe.execute()

    def _normalize_event_for_storage(self, event: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(event) if isinstance(event, dict) else {}
        payload = normalized.get("data")
        data = dict(payload) if isinstance(payload, dict) else {}
        data.setdefault("conversationId", self.conversation_id)
        data.setdefault("runMessageId", self.user_message_id)
        if self.run_id:
            data.setdefault("runId", self.run_id)
        normalized["data"] = data
        return normalized

    async def update_step(self, step: str) -> None:
        """HSET current_step in Redis metadata hash."""
        self.current_step = step
        r = await get_async_redis()
        meta_key = _META_KEY.format(conv_id=self.conversation_id)
        user_streams_key = _USER_STREAMS_KEY.format(user_id=self.user_id)
        pipe = r.pipeline()
        pipe.hset(meta_key, "current_step", step)
        pipe.expire(meta_key, _STREAM_INITIAL_TTL)
        pipe.expire(user_streams_key, _USER_STREAMS_TTL)
        await pipe.execute()

    async def check_cancel(self) -> bool:
        """Check if cancellation was requested (EXISTS on cancel key)."""
        r = await get_async_redis()
        cancel_key = _CANCEL_KEY.format(conv_id=self.conversation_id)
        return bool(await r.exists(cancel_key))

    async def set_status(self, status: str) -> None:
        """HSET status in Redis metadata hash."""
        self.status = status
        r = await get_async_redis()
        meta_key = _META_KEY.format(conv_id=self.conversation_id)
        user_streams_key = _USER_STREAMS_KEY.format(user_id=self.user_id)
        pipe = r.pipeline()
        pipe.hset(meta_key, "status", status)
        pipe.expire(meta_key, _STREAM_INITIAL_TTL)
        pipe.expire(user_streams_key, _USER_STREAMS_TTL)
        await pipe.execute()

    async def touch(self) -> None:
        """Refresh TTLs for active stream keys without emitting an event."""
        r = await get_async_redis()
        events_key = _EVENTS_KEY.format(conv_id=self.conversation_id)
        meta_key = _META_KEY.format(conv_id=self.conversation_id)
        index_key = _EVENT_ID_INDEX_KEY.format(conv_id=self.conversation_id)
        user_streams_key = _USER_STREAMS_KEY.format(user_id=self.user_id)
        pipe = r.pipeline()
        pipe.expire(events_key, _STREAM_INITIAL_TTL)
        pipe.expire(meta_key, _STREAM_INITIAL_TTL)
        pipe.expire(index_key, _STREAM_INITIAL_TTL)
        pipe.expire(user_streams_key, _USER_STREAMS_TTL)
        await pipe.execute()


# ── Local stream registry (producing worker only) ────────────────────────

_local_streams: Dict[str, ChatStream] = {}


def get_local_stream(conversation_id: str) -> Optional[ChatStream]:
    """Look up a stream on this worker (producing worker only)."""
    return _local_streams.get(conversation_id)


def get_all_local_streams() -> Dict[str, ChatStream]:
    """Get all local streams (for graceful shutdown)."""
    return dict(_local_streams)


async def publish_user_event(user_id: str, payload: Dict[str, Any]) -> None:
    """Publish a user-scoped event onto the shared lifecycle/event bus."""
    if not isinstance(user_id, str) or not user_id.strip():
        return
    if not isinstance(payload, dict) or not payload:
        return

    try:
        normalized_payload = validate_chat_user_event_payload(payload)
        r = await get_async_redis()
        user_channel = _USER_EVENTS_CHANNEL.format(user_id=user_id.strip())
        await r.publish(user_channel, json.dumps(normalized_payload, default=str))
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.user_events.publish_failed",
            "retry",
            user_id=user_id,
            event_type=str(payload.get("type", "")),
            exc_info=True,
        )


# ── Redis-backed stream functions (work from any worker) ─────────────────

async def register_stream(
    conversation_id: str,
    user_id: str,
    user_message_id: str,
    run_id: Optional[str],
    task: asyncio.Task,
    context: Optional[StreamContext] = None,
    current_step: Optional[str] = None,
) -> ChatStream:
    """Create a local ChatStream and register it in Redis.

    1. Create local ChatStream in _local_streams
    2. HSET assist:stream:meta:{conv_id}
    3. SADD assist:user:streams:{user_id}
    4. PUBLISH assist:user:events:{user_id} stream_started
    """
    stream = ChatStream(
        conversation_id=conversation_id,
        user_id=user_id,
        user_message_id=user_message_id,
        run_id=run_id,
        task=task,
        context=context,
        current_step=current_step,
    )
    r = await get_async_redis()
    events_key = _EVENTS_KEY.format(conv_id=conversation_id)
    meta_key = _META_KEY.format(conv_id=conversation_id)
    index_key = _EVENT_ID_INDEX_KEY.format(conv_id=conversation_id)
    cancel_key = _CANCEL_KEY.format(conv_id=conversation_id)
    user_streams_key = _USER_STREAMS_KEY.format(user_id=user_id)
    register_lock_key = _REGISTER_LOCK_KEY.format(conv_id=conversation_id)
    lock_token = str(uuid4())

    user_channel = _USER_EVENTS_CHANNEL.format(user_id=user_id)
    register_channel = _CONVERSATION_REGISTER_CHANNEL.format(conv_id=conversation_id)
    lifecycle_event = json.dumps({
        "type": "stream_started",
        "conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "run_id": run_id,
        "status": "running",
        "current_step": stream.current_step,
        "started_at": stream.started_at.isoformat(),
    })

    acquired = bool(
        await r.set(
            register_lock_key,
            lock_token,
            ex=_REGISTER_LOCK_TTL,
            nx=True,
        )
    )
    if not acquired:
        raise StreamRegistrationConflictError("Stream registration already in progress")

    try:
        existing_status = await r.hget(meta_key, "status")
        if existing_status in _ACTIVE_STREAM_STATUSES:
            raise StreamRegistrationConflictError(
                f"Conversation already has an active stream ({existing_status})",
            )

        pipe = r.pipeline()
        # Reset previous stream buffer for this conversation so each submit starts
        # with a clean event timeline (event IDs restart from 1 per stream run).
        pipe.delete(events_key)
        pipe.delete(index_key)
        pipe.delete(cancel_key)
        pipe.hset(meta_key, mapping={
            "user_id": user_id,
            "user_message_id": user_message_id,
            "run_id": run_id or "",
            "status": "running",
            "last_stream_event_id": "0",
            "started_at": stream.started_at.isoformat(),
            "worker_id": _WORKER_ID,
            "current_step": "",
        })
        pipe.expire(meta_key, _STREAM_INITIAL_TTL)
        pipe.expire(events_key, _STREAM_INITIAL_TTL)
        pipe.expire(index_key, _STREAM_INITIAL_TTL)
        pipe.sadd(user_streams_key, conversation_id)
        pipe.expire(user_streams_key, _USER_STREAMS_TTL)
        pipe.publish(register_channel, json.dumps({
            "type": "stream_registered",
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "run_id": run_id,
            "status": "running",
        }))
        pipe.publish(user_channel, lifecycle_event)
        await pipe.execute()
        _local_streams[conversation_id] = stream
    finally:
        try:
            await r.eval(_RELEASE_REGISTER_LOCK_LUA, 1, register_lock_key, lock_token)
        except Exception:
            log_event(
                logger,
                "WARNING",
                "chat.stream.register_lock_release_failed",
                "retry",
                conversation_id=conversation_id,
                user_id=user_id,
            )

    log_event(
        logger,
        "INFO",
        "chat.stream.registered_local",
        "timing",
        conversation_id=conversation_id,
        user_id=user_id,
    )
    return stream


async def schedule_cleanup(conversation_id: str, delay: Optional[int] = None) -> None:
    """Finalize a stream: publish lifecycle event, set TTLs, remove from user set.

    Called after stream completion/failure/cancellation.
    """
    if delay is None:
        delay = settings.redis_stream_grace_period

    stream = _local_streams.get(conversation_id)
    r = await get_async_redis()
    meta_key = _META_KEY.format(conv_id=conversation_id)

    # Determine user_id and status from local stream or Redis meta
    if stream:
        user_id = stream.user_id
        status = stream.status
        run_id = stream.run_id
        user_message_id = stream.user_message_id
        current_step = stream.current_step
    else:
        meta = await r.hgetall(meta_key)
        user_id = meta.get("user_id", "")
        status = meta.get("status", "unknown")
        run_id = meta.get("run_id", "") or None
        user_message_id = meta.get("user_message_id", "") or None
        current_step = meta.get("current_step", "") or None

    # Set TTLs, publish lifecycle, and clean up user set in one pipeline.
    events_key = _EVENTS_KEY.format(conv_id=conversation_id)
    index_key = _EVENT_ID_INDEX_KEY.format(conv_id=conversation_id)
    pipe = r.pipeline()
    pipe.expire(events_key, delay)
    pipe.expire(index_key, delay)
    pipe.expire(meta_key, delay)

    if user_id:
        if status in ("completed", "cancelled"):
            event_type = "stream_completed"
        elif status == "paused":
            event_type = "stream_paused"
        elif status == "resumed":
            event_type = "stream_resumed"
        else:
            event_type = "stream_failed"
        user_channel = _USER_EVENTS_CHANNEL.format(user_id=user_id)
        lifecycle_event = json.dumps({
            "type": event_type,
            "conversation_id": conversation_id,
            "status": status,
            "run_id": run_id,
            "user_message_id": user_message_id,
            "current_step": current_step,
        })
        pipe.publish(user_channel, lifecycle_event)
        user_streams_key = _USER_STREAMS_KEY.format(user_id=user_id)
        pipe.srem(user_streams_key, conversation_id)

    await pipe.execute()

    # Remove from local registry
    _local_streams.pop(conversation_id, None)
    log_event(
        logger,
        "DEBUG",
        "chat.stream.cleanup_scheduled",
        "timing",
        conversation_id=conversation_id,
        ttl_seconds=delay,
    )


async def get_stream_meta(conversation_id: str) -> Optional[Dict[str, str]]:
    """HGETALL on the stream metadata hash. Returns None if no meta exists."""
    r = await get_async_redis()
    meta_key = _META_KEY.format(conv_id=conversation_id)
    meta = await r.hgetall(meta_key)
    return meta if meta else None


async def get_stream_status(conversation_id: str) -> Optional[str]:
    """HGET status from stream metadata. Returns None if no stream."""
    r = await get_async_redis()
    meta_key = _META_KEY.format(conv_id=conversation_id)
    return await r.hget(meta_key, "status")


async def get_active_streams_for_user(user_id: str) -> List[Dict[str, Any]]:
    """Get all active streams for a user (works from any worker).

    Reads the user's active streams set, then fetches metadata for each.
    """
    r = await get_async_redis()
    user_streams_key = _USER_STREAMS_KEY.format(user_id=user_id)
    raw_conv_ids = await r.smembers(user_streams_key)
    if not raw_conv_ids:
        return []

    conv_ids: List[str] = []
    for raw in raw_conv_ids:
        if isinstance(raw, bytes):
            decoded = raw.decode("utf-8", errors="ignore").strip()
        else:
            decoded = str(raw).strip()
        if decoded:
            conv_ids.append(decoded)
    if not conv_ids:
        return []

    pipe = r.pipeline()
    for conv_id in conv_ids:
        meta_key = _META_KEY.format(conv_id=conv_id)
        pipe.hgetall(meta_key)
    raw_meta_rows = await pipe.execute()

    result = []
    stale_conv_ids: List[str] = []
    for conv_id, raw_meta in zip(conv_ids, raw_meta_rows):
        if isinstance(raw_meta, dict):
            meta = {
                (k.decode("utf-8", errors="ignore") if isinstance(k, bytes) else str(k)): (
                    v.decode("utf-8", errors="ignore") if isinstance(v, bytes) else str(v)
                )
                for k, v in raw_meta.items()
            }
        else:
            meta = {}
        if meta and meta.get("status") == "running":
            result.append({
                "conversation_id": conv_id,
                "user_message_id": meta.get("user_message_id", ""),
                "run_id": meta.get("run_id", "") or None,
                "started_at": meta.get("started_at"),
                "current_step": meta.get("current_step") or None,
            })
        else:
            stale_conv_ids.append(conv_id)

    if stale_conv_ids:
        # Batch stale set cleanup to avoid per-conversation Redis round-trips.
        await r.srem(user_streams_key, *stale_conv_ids)

    return result


async def request_cancel(conversation_id: str) -> None:
    """Set the cancellation flag in Redis."""
    r = await get_async_redis()
    cancel_key = _CANCEL_KEY.format(conv_id=conversation_id)
    await r.set(cancel_key, "1", ex=_CANCEL_TTL)
    log_event(
        logger,
        "INFO",
        "chat.stream.cancel_flag_set",
        "timing",
        conversation_id=conversation_id,
    )


async def wait_for_stream_registration(
    *,
    conversation_id: str,
    user_id: str,
    timeout_seconds: float = 2.0,
) -> Optional[Dict[str, str]]:
    """Wait for stream metadata creation without polling loops.

    Uses conversation-scoped registration signals so authorized collaborators
    can attach to the same live stream as the owner.
    """
    _ = user_id
    existing = await get_stream_meta(conversation_id)
    if existing:
        return existing

    timeout = max(0.1, float(timeout_seconds))
    deadline = monotonic() + timeout
    r = await get_async_redis()
    pubsub = r.pubsub()
    channel = _CONVERSATION_REGISTER_CHANNEL.format(conv_id=conversation_id)

    try:
        await pubsub.subscribe(channel)
        while monotonic() < deadline:
            remaining = max(0.0, deadline - monotonic())
            if remaining <= 0:
                break
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=min(remaining, 1.0),
            )
            if not message:
                continue
            try:
                payload = json.loads(message.get("data", ""))
            except Exception:
                continue
            if (
                isinstance(payload, dict)
                and payload.get("type") == "stream_registered"
                and payload.get("conversation_id") == conversation_id
            ):
                break
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass

    meta = await get_stream_meta(conversation_id)
    return meta


async def wait_for_stream_stop(
    *,
    conversation_id: str,
    timeout_seconds: float = 8.0,
) -> Optional[str]:
    """Wait for a running stream to stop using Redis Stream blocking reads."""
    r = await get_async_redis()
    meta_key = _META_KEY.format(conv_id=conversation_id)
    status_cache_ttl_seconds = 2.5
    cached_status: Optional[str] = None
    cached_at = 0.0

    async def _read_status(*, refresh: bool = False) -> Optional[str]:
        nonlocal cached_status, cached_at
        now = monotonic()
        if not refresh and cached_status is not None and (now - cached_at) < status_cache_ttl_seconds:
            return cached_status
        raw_status = await r.hget(meta_key, "status")
        if raw_status is None:
            cached_status = None
            cached_at = now
            return cached_status
        if isinstance(raw_status, bytes):
            cached_status = raw_status.decode("utf-8", errors="ignore")
        else:
            cached_status = str(raw_status)
        cached_at = now
        return cached_status

    status = await _read_status(refresh=True)
    if status != "running":
        return status

    timeout = max(0.5, float(timeout_seconds))
    deadline = monotonic() + timeout
    events_key = _EVENTS_KEY.format(conv_id=conversation_id)
    last_stream_id = "$"
    terminal_types = {"done", "error", "run.failed"}

    while monotonic() < deadline:
        remaining_ms = int(max(1.0, (deadline - monotonic()) * 1000.0))
        result = await r.xread(
            {events_key: last_stream_id},
            block=min(remaining_ms, 2000),
            count=100,
        )
        if not result:
            status = await _read_status()
            if status != "running":
                return status
            continue
        for _stream_name, entries in result:
            for entry_id, entry_data in entries:
                last_stream_id = entry_id
                try:
                    event = json.loads(entry_data["data"])
                except Exception:
                    continue
                if isinstance(event, dict) and event.get("type") in terminal_types:
                    status = await _read_status(refresh=True)
                    return status if status else "completed"

    return await _read_status(refresh=True)


# ── Stream event subscriber for browser transport replay/live reads ──────


def _normalize_stream_entry_id(value: Any) -> Optional[str]:
    """Return a safe Redis stream entry ID or None when the value is invalid."""
    if value is None:
        return None
    if isinstance(value, bytes):
        candidate = value.decode("utf-8", errors="ignore").strip()
    else:
        candidate = str(value).strip()
    if not candidate:
        return None
    if _STREAM_ENTRY_ID_RE.fullmatch(candidate):
        return candidate
    return None


def _exclusive_xrange_min(stream_id: Optional[str]) -> str:
    normalized_stream_id = _normalize_stream_entry_id(stream_id)
    if normalized_stream_id is None:
        return "0-0"
    return f"({normalized_stream_id}"


async def subscribe_stream_events(
    conversation_id: str,
    since_stream_event_id: int = 0,
    *,
    user_id: Optional[str] = None,
    requested_run_message_id: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Async generator yielding replay + live events from a Redis Stream.

    Access control is enforced before this helper is called. Redis stream
    metadata is not treated as the read authorization boundary.
    """
    r = await get_async_redis()
    events_key = _EVENTS_KEY.format(conv_id=conversation_id)
    meta_key = _META_KEY.format(conv_id=conversation_id)
    index_key = _EVENT_ID_INDEX_KEY.format(conv_id=conversation_id)
    cached_meta: Optional[Dict[str, str]] = None
    cached_status: Optional[str] = None

    async def _load_meta(*, refresh: bool = False) -> Dict[str, str]:
        nonlocal cached_meta, cached_status
        if cached_meta is not None and not refresh:
            return cached_meta
        raw_meta = await r.hgetall(meta_key)
        if isinstance(raw_meta, dict):
            cached_meta = {
                (k.decode("utf-8", errors="ignore") if isinstance(k, bytes) else str(k)): (
                    v.decode("utf-8", errors="ignore") if isinstance(v, bytes) else str(v)
                )
                for k, v in raw_meta.items()
            }
        else:
            cached_meta = {}
        cached_status = cached_meta.get("status")
        return cached_meta

    async def _get_status(*, refresh: bool = False) -> Optional[str]:
        nonlocal cached_status, cached_meta
        if cached_status is not None and not refresh:
            return cached_status
        raw_status = await r.hget(meta_key, "status")
        if raw_status is None:
            cached_status = None
        elif isinstance(raw_status, bytes):
            cached_status = raw_status.decode("utf-8", errors="ignore")
        else:
            cached_status = str(raw_status)
        if cached_meta is not None:
            if cached_status is None:
                cached_meta.pop("status", None)
            else:
                cached_meta["status"] = cached_status
        return cached_status

    _ = user_id

    last_stream_id: Optional[str] = None
    replay_start_stream_id: Optional[str] = "0-0"
    live_cursor = "0-0"
    should_emit_replay_gap = False

    terminal_types = {"done", "error", "run.failed"}

    def _event_matches_requested_run(event: Any) -> bool:
        if not requested_run_message_id:
            return True
        if not isinstance(event, dict):
            return False
        data = event.get("data")
        if not isinstance(data, dict):
            return True
        event_run_message_id = data.get("runMessageId")
        if not isinstance(event_run_message_id, str) or not event_run_message_id.strip():
            return True
        return event_run_message_id.strip() == requested_run_message_id

    if since_stream_event_id > 0:
        raw_mapped_stream_id = await r.hget(index_key, str(since_stream_event_id))
        mapped_stream_id = _normalize_stream_entry_id(raw_mapped_stream_id)
        if mapped_stream_id:
            replay_start_stream_id = mapped_stream_id
            live_cursor = mapped_stream_id
        else:
            if raw_mapped_stream_id is not None:
                log_event(
                    logger,
                    "WARNING",
                    "chat.stream.invalid_indexed_cursor",
                    "retry",
                    conversation_id=conversation_id,
                    since_stream_event_id=since_stream_event_id,
                    raw_cursor_type=type(raw_mapped_stream_id).__name__,
                    raw_cursor_value=str(raw_mapped_stream_id),
                )
            raw_last_stream_event_id = (await _load_meta()).get("last_stream_event_id")
            try:
                last_stream_event_id = int(raw_last_stream_event_id) if raw_last_stream_event_id is not None else 0
            except (TypeError, ValueError):
                last_stream_event_id = 0
            if last_stream_event_id > since_stream_event_id:
                should_emit_replay_gap = True
            replay_start_stream_id = None
            live_cursor = "$"

    if should_emit_replay_gap:
        yield {
            "id": since_stream_event_id + 1,
            "type": "replay_gap",
            "data": {
                "expectedNextStreamEventId": since_stream_event_id + 1,
                "reason": "cursor_not_available",
            },
        }

    # Phase 1: Replay from mapped cursor only (or from start for fresh connect).
    if replay_start_stream_id is not None:
        replay_min = "0-0" if replay_start_stream_id == "0-0" else f"({replay_start_stream_id}"
        entries = await r.xrange(events_key, min=replay_min)
        for entry_id, entry_data in entries:
            normalized_entry_id = _normalize_stream_entry_id(entry_id)
            if normalized_entry_id is None:
                log_event(
                    logger,
                    "WARNING",
                    "chat.stream.invalid_replay_entry_id",
                    "retry",
                    conversation_id=conversation_id,
                    phase="replay",
                    raw_stream_entry_id=str(entry_id),
                )
                continue
            try:
                event = json.loads(entry_data["data"])
            except Exception:
                log_event(
                    logger,
                    "WARNING",
                    "chat.stream.event_decode_failed",
                    "retry",
                    conversation_id=conversation_id,
                    stream_entry_id=entry_id,
                    phase="replay",
                )
                continue
            last_stream_id = normalized_entry_id
            if not _event_matches_requested_run(event):
                continue
            event_id = event.get("id", 0)
            event_type = event.get("type", "")
            if event_id > since_stream_event_id:
                yield event
            if event_type in terminal_types:
                return

    # Check if stream already completed before entering live phase
    status = await _get_status()
    if status in ("completed", "failed", "cancelled"):
        # Final drain. If reconnect did not retain a usable Redis stream
        # cursor, scan from the start and re-apply event-id filtering.
        entries = await r.xrange(events_key, min=_exclusive_xrange_min(last_stream_id))
        for entry_id, entry_data in entries:
            normalized_entry_id = _normalize_stream_entry_id(entry_id)
            if normalized_entry_id is None:
                log_event(
                    logger,
                    "WARNING",
                    "chat.stream.invalid_replay_entry_id",
                    "retry",
                    conversation_id=conversation_id,
                    phase="final_drain_pre_live",
                    raw_stream_entry_id=str(entry_id),
                )
                continue
            try:
                event = json.loads(entry_data["data"])
            except Exception:
                log_event(
                    logger,
                    "WARNING",
                    "chat.stream.event_decode_failed",
                    "retry",
                    conversation_id=conversation_id,
                    stream_entry_id=entry_id,
                    phase="final_drain_pre_live",
                )
                continue
            last_stream_id = normalized_entry_id
            if not _event_matches_requested_run(event):
                continue
            event_id = event.get("id", 0)
            if event_id > since_stream_event_id:
                yield event
        return

    # Phase 2: Live events via XREAD BLOCK
    while True:
        block_ms = max(1000, int(getattr(settings, "redis_stream_xread_block_ms", 10000) or 10000))
        try:
            result = await r.xread(
                {events_key: last_stream_id or live_cursor},
                block=block_ms,
                count=100,
            )
        except redis.exceptions.TimeoutError:
            log_event(
                logger,
                "INFO",
                "chat.stream.live_read_timeout_recovered",
                "retry",
                conversation_id=conversation_id,
                last_stream_id=last_stream_id,
                block_ms=block_ms,
            )
            result = []

        if not result:
            # Check if the stream ended while we were blocking.
            status = await _get_status(refresh=True)
            if status in ("completed", "failed", "cancelled"):
                # Final drain
                entries = await r.xrange(events_key, min=_exclusive_xrange_min(last_stream_id))
                for entry_id, entry_data in entries:
                    normalized_entry_id = _normalize_stream_entry_id(entry_id)
                    if normalized_entry_id is None:
                        log_event(
                            logger,
                            "WARNING",
                            "chat.stream.invalid_replay_entry_id",
                            "retry",
                            conversation_id=conversation_id,
                            phase="final_drain_post_timeout",
                            raw_stream_entry_id=str(entry_id),
                        )
                        continue
                    try:
                        event = json.loads(entry_data["data"])
                    except Exception:
                        log_event(
                            logger,
                            "WARNING",
                            "chat.stream.event_decode_failed",
                            "retry",
                            conversation_id=conversation_id,
                            stream_entry_id=entry_id,
                            phase="final_drain_post_timeout",
                        )
                        continue
                    last_stream_id = normalized_entry_id
                    if not _event_matches_requested_run(event):
                        continue
                    event_id = event.get("id", 0)
                    if event_id > since_stream_event_id:
                        yield event
                return
            continue

        # Process received entries
        for stream_name, entries in result:
            for entry_id, entry_data in entries:
                normalized_entry_id = _normalize_stream_entry_id(entry_id)
                if normalized_entry_id is None:
                    log_event(
                        logger,
                        "WARNING",
                        "chat.stream.invalid_live_entry_id",
                        "retry",
                        conversation_id=conversation_id,
                        phase="live",
                        raw_stream_entry_id=str(entry_id),
                    )
                    continue
                try:
                    event = json.loads(entry_data["data"])
                except Exception:
                    log_event(
                        logger,
                        "WARNING",
                        "chat.stream.event_decode_failed",
                        "retry",
                        conversation_id=conversation_id,
                        stream_entry_id=entry_id,
                        phase="live",
                    )
                    continue
                last_stream_id = normalized_entry_id
                if not _event_matches_requested_run(event):
                    continue
                event_id = event.get("id", 0)
                event_type = event.get("type", "")
                if event_id > since_stream_event_id:
                    yield event
                if event_type in terminal_types:
                    return


# ── User lifecycle subscriber for worker-local fan-out ───────────────────
# Uses 1 Redis PSUBSCRIBE connection per worker, fan-out to local queues.

_local_user_subscribers: Dict[str, List[asyncio.Queue]] = {}
_user_listener_task: Optional[asyncio.Task] = None
_user_listener_lock = asyncio.Lock()


async def _run_user_event_listener() -> None:
    """Run the shared Redis user-event listener loop for this worker."""
    try:
        r = await get_async_redis()
        pubsub = r.pubsub()
        await pubsub.psubscribe("assist:user:events:*")
        log_event(
            logger,
            "INFO",
            "chat.user_events.listener_started",
            "timing",
            channel_pattern="assist:user:events:*",
        )

        async for message in pubsub.listen():
            if message["type"] != "pmessage":
                continue

            channel = message["channel"]
            # Extract user_id from channel: assist:user:events:{user_id}
            user_id = channel.split(":")[-1]
            data_str = message["data"]

            queues = _local_user_subscribers.get(user_id)
            if not queues:
                continue

            try:
                event = json.loads(data_str)
            except (json.JSONDecodeError, TypeError):
                continue

            for queue in list(queues):
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    log_event(
                        logger,
                        "WARNING",
                        "chat.user_events.queue_full",
                        "retry",
                        user_id=user_id,
                    )

    except asyncio.CancelledError:
        log_event(logger, "INFO", "chat.user_events.listener_cancelled", "timing")
        raise
    except Exception:
        log_event(logger, "ERROR", "chat.user_events.listener_crashed", "error", exc_info=True)


async def _start_user_event_listener() -> None:
    """Start a single PSUBSCRIBE listener task for this worker.

    Subscribes to assist:user:events:* and routes messages to
    local asyncio.Queues keyed by user_id.
    """
    global _user_listener_task
    if _user_listener_task is not None and not _user_listener_task.done():
        return

    async with _user_listener_lock:
        if _user_listener_task is not None and not _user_listener_task.done():
            return
        _user_listener_task = asyncio.create_task(_run_user_event_listener())


def subscribe_user(user_id: str) -> asyncio.Queue:
    """Subscribe to lifecycle events for a user. Returns a queue to await on.

    Lazily starts the PSUBSCRIBE listener task if not already running.
    """
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _local_user_subscribers.setdefault(user_id, []).append(queue)

    # Ensure listener is running (fire-and-forget — it's idempotent)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_start_user_event_listener())
    except RuntimeError:
        pass

    return queue


def unsubscribe_user(user_id: str, queue: asyncio.Queue) -> None:
    """Remove a user subscriber queue."""
    queues = _local_user_subscribers.get(user_id)
    if queues:
        try:
            queues.remove(queue)
        except ValueError:
            pass
        if not queues:
            del _local_user_subscribers[user_id]


async def shutdown_user_listener() -> None:
    """Cancel the PSUBSCRIBE listener task (called from main.py shutdown)."""
    global _user_listener_task
    if _user_listener_task is not None and not _user_listener_task.done():
        _user_listener_task.cancel()
        try:
            await _user_listener_task
        except asyncio.CancelledError:
            pass
        _user_listener_task = None
        log_event(logger, "INFO", "chat.user_events.listener_shutdown", "timing")
