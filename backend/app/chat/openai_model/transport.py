"""Provider transport/client helpers for OpenAI Responses streaming."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import aiohttp

try:
    from openai import AsyncOpenAI, OpenAI  # type: ignore
except Exception:  # pragma: no cover - OpenAI SDK may be absent in some environments
    AsyncOpenAI = None  # type: ignore
    OpenAI = None  # type: ignore

from ...config.settings import settings


_OPENAI_RESPONSES_WS_URL = "wss://api.openai.com/v1/responses"
_OPENAI_WS_TERMINAL_EVENTS = frozenset(
    {
        "response.completed",
        "response.failed",
        "response.incomplete",
        "response.error",
        "error",
    }
)

def normalize_provider_name(raw: Optional[str]) -> str:
    normalized = str(raw or "").strip().lower()
    if normalized == "openai":
        return normalized
    return "openai"


def get_openai_api_key() -> str:
    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server")
    return api_key


async def open_openai_responses_websocket() -> tuple[aiohttp.ClientSession, aiohttp.ClientWebSocketResponse]:
    api_key = get_openai_api_key()
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None))
    try:
        ws = await session.ws_connect(
            _OPENAI_RESPONSES_WS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            heartbeat=30,
        )
    except Exception:
        await session.close()
        raise
    return session, ws


async def stream_openai_ws_turn(
    *,
    ws: aiohttp.ClientWebSocketResponse,
    payload: Dict[str, Any],
) -> AsyncGenerator[Dict[str, Any], None]:
    await ws.send_str(json.dumps(payload))

    while True:
        message = await ws.receive()
        if message.type == aiohttp.WSMsgType.TEXT:
            raw_data = message.data
            if not isinstance(raw_data, str) or not raw_data.strip():
                continue
            try:
                event = json.loads(raw_data)
            except Exception:
                continue
            if not isinstance(event, dict):
                continue
            yield event
            event_type = event.get("type")
            if isinstance(event_type, str) and event_type in _OPENAI_WS_TERMINAL_EVENTS:
                return
            continue

        if message.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED}:
            raise RuntimeError("OpenAI websocket connection closed")

        if message.type == aiohttp.WSMsgType.ERROR:
            raise RuntimeError(f"OpenAI websocket connection error: {ws.exception()}")


# ---------------------------------------------------------------------------
# Sync OpenAI client (lazily created) — used for lightweight REST helpers
# (token counting + compact) that are called via run_in_executor.
# ---------------------------------------------------------------------------

_sync_openai_client: Optional["OpenAI"] = None


def _get_sync_openai_client() -> "OpenAI":
    global _sync_openai_client
    if _sync_openai_client is not None:
        return _sync_openai_client
    if OpenAI is None:
        raise RuntimeError("OpenAI SDK is not available in this environment")
    api_key = get_openai_api_key()
    _sync_openai_client = OpenAI(api_key=api_key)
    return _sync_openai_client


def _count_tokens_sync(
    model: str,
    input_items: List[Dict[str, Any]],
    instructions: Optional[str],
    tools: Optional[List[Dict[str, Any]]],
) -> int:
    client = _get_sync_openai_client()
    kwargs: Dict[str, Any] = {"model": model, "input": input_items}
    if instructions:
        kwargs["instructions"] = instructions
    if tools:
        kwargs["tools"] = tools
    result = client.responses.input_tokens.count(**kwargs)
    return result.input_tokens


def _compact_sync(
    model: str,
    input_items: List[Dict[str, Any]],
    instructions: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    client = _get_sync_openai_client()
    kwargs: Dict[str, Any] = {"model": model, "input": input_items}
    if instructions:
        kwargs["instructions"] = instructions
    result = client.responses.compact(**kwargs)
    output: List[Dict[str, Any]] = []
    for item in result.output:
        # The compact endpoint returns content blocks with type='input_text'
        # but the SDK model expects 'output_text', causing Pydantic
        # serialization warnings. Suppress via warnings=False.
        d = item.model_dump(warnings=False) if hasattr(item, "model_dump") else {}
        output.append(d)
    usage = {
        "input_tokens": result.usage.input_tokens if result.usage else 0,
        "output_tokens": result.usage.output_tokens if result.usage else 0,
    }
    return output, usage


async def count_openai_input_tokens(
    model: str,
    input_items: List[Dict[str, Any]],
    instructions: Optional[str],
    tools: Optional[List[Dict[str, Any]]],
) -> int:
    """Count exact input tokens via the OpenAI token counting API."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _count_tokens_sync, model, input_items, instructions, tools,
    )


async def compact_openai_input(
    model: str,
    input_items: List[Dict[str, Any]],
    instructions: Optional[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Compact input items via the standalone /responses/compact endpoint.

    Returns (output_items, usage_dict).
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _compact_sync, model, input_items, instructions,
    )
