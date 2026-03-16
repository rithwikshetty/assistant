"""
Redis client utilities.

Provides sync and async Redis clients. The async client backs chat event
streaming (Redis Streams + Pub/Sub) and any future async Redis needs.
The sync client is used by backend-managed synchronous Redis flows.
"""
import logging
from typing import Optional

import redis
import redis.asyncio as aioredis

from ..config.settings import settings
from ..logging import log_event

logger = logging.getLogger(__name__)


# ── Synchronous Redis client (backend-managed flows) ───────────────────
_sync_redis: Optional[redis.Redis] = None


def get_sync_redis() -> redis.Redis:
    """Get synchronous Redis client for backend-managed flows."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = redis.from_url(settings.redis_url, decode_responses=True)
    return _sync_redis


# ── Async Redis client (for FastAPI) ───────────────────────────────────
_async_redis: Optional[aioredis.Redis] = None


def _async_socket_timeout_seconds() -> float:
    block_seconds = max(
        1.0,
        float(getattr(settings, "redis_stream_xread_block_ms", 10000) or 10000) / 1000.0,
    )
    # Keep a clear margin above XREAD BLOCK so an idle blocking read is not
    # misclassified as a socket-level timeout.
    return max(30.0, block_seconds + 5.0)


async def get_async_redis() -> aioredis.Redis:
    """Get async Redis client for FastAPI endpoints.

    Uses a connection pool with configurable size and timeouts
    to support concurrent XREAD BLOCK, PSUBSCRIBE, and transient
    command connections.
    """
    global _async_redis
    if _async_redis is None:
        _async_redis = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=settings.redis_max_connections,
            socket_connect_timeout=5,
            socket_timeout=_async_socket_timeout_seconds(),
            retry_on_timeout=True,
        )
    return _async_redis


async def close_async_redis() -> None:
    """Close the async Redis connection pool.

    Call during application shutdown to release all connections cleanly.
    """
    global _async_redis
    if _async_redis is not None:
        await _async_redis.aclose()
        _async_redis = None
        log_event(logger, "INFO", "redis.async_pool.closed", "timing")
