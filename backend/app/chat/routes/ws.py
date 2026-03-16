"""Authenticated chat WebSocket transport.

Browser clients connect once per session and multiplex:
- user lifecycle events (active streams, title updates)
- per-conversation runtime stream events

This follows the same broad transport pattern as `t3code`:
- one authenticated WebSocket
- request/response envelopes for control messages
- push envelopes for server-originated events
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import anyio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from ...auth.local_user import get_or_create_local_user_async
from ...config.database import AsyncSessionLocal
from ...config.settings import settings
from ...database.models import User
from ...logging import log_event
from ...services.chat_streams import (
    get_active_streams_for_user,
    get_stream_meta,
    subscribe_stream_events,
    subscribe_user,
    unsubscribe_user,
    wait_for_stream_registration,
)
from ...utils.coerce import normalize_non_empty_string
from ...utils.jsonlib import json_dumps
from ..services.cancel_stream_service import cancel_conversation_stream
from ..services.run_runtime_service import require_accessible_conversation_async
from ..ws_contract import (
    CHAT_WS_CHANNELS,
    CHAT_WS_METHODS,
    ChatWsConversationRequestBody,
    ChatWsPingBody,
    ChatWsSubscribeStreamBody,
    build_chat_ws_push,
    build_chat_ws_response,
    parse_chat_ws_request,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_SOCKET_RESOURCE_CLOSED_EXCEPTIONS = (
    anyio.BrokenResourceError,
    anyio.ClosedResourceError,
)


async def _authenticate_websocket_user(websocket: WebSocket) -> Optional[User]:
    async with AsyncSessionLocal() as auth_db:
        try:
            return await get_or_create_local_user_async(auth_db)
        except Exception:
            await websocket.close(
                code=status.WS_1008_POLICY_VIOLATION,
                reason="Workspace user unavailable",
            )
            return None


async def _require_websocket_conversation_access(user: User, conversation_id: str) -> None:
    async with AsyncSessionLocal() as authz_db:
        await require_accessible_conversation_async(
            authz_db,
            current_user=user,
            conversation_id=conversation_id,
        )


def _resolve_request_error_message(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        message = normalize_non_empty_string(str(exc))
        return message or "Request failed"
    if isinstance(exc, HTTPException):
        detail = normalize_non_empty_string(exc.detail)
        return detail or "Request failed"
    return "Request failed"


@dataclass
class _SocketState:
    websocket: WebSocket
    user: User
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    stream_tasks: Dict[str, asyncio.Task[None]] = field(default_factory=dict)
    user_queue: Optional[asyncio.Queue] = None
    user_task: Optional[asyncio.Task[None]] = None


async def _send_json(state: _SocketState, payload: Dict[str, Any]) -> None:
    async with state.send_lock:
        await state.websocket.send_text(json_dumps(payload))


async def _send_response(state: _SocketState, *, request_id: str, result: Any = None, error: Optional[str] = None) -> None:
    await _send_json(
        state,
        build_chat_ws_response(request_id=request_id, result=result, error=error),
    )


async def _send_push(state: _SocketState, *, channel: str, data: Any) -> None:
    await _send_json(state, build_chat_ws_push(channel=channel, data=data))


async def _send_initial_user_state(state: _SocketState) -> None:
    active = await get_active_streams_for_user(str(state.user.id))
    await _send_push(
        state,
        channel=CHAT_WS_CHANNELS["user_event"],
        data={
            "type": "initial_state",
            "streams": active,
        },
    )


async def _relay_user_events(state: _SocketState, queue: asyncio.Queue) -> None:
    try:
        while True:
            event = await queue.get()
            if not isinstance(event, dict):
                continue
            await _send_push(
                state,
                channel=CHAT_WS_CHANNELS["user_event"],
                data=event,
            )
    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        pass
    except _SOCKET_RESOURCE_CLOSED_EXCEPTIONS:
        pass
    except RuntimeError:
        pass
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.ws.user_event_relay_failed",
            "retry",
            user_id=str(state.user.id),
            exc_info=True,
        )


async def _cancel_stream_task(state: _SocketState, conversation_id: str) -> None:
    existing = state.stream_tasks.pop(conversation_id, None)
    if existing is None:
        return
    existing.cancel()
    await asyncio.gather(existing, return_exceptions=True)


async def _relay_conversation_stream(
    state: _SocketState,
    *,
    conversation_id: str,
    since_stream_event_id: int,
    run_message_id: Optional[str],
) -> None:
    user_id = str(state.user.id)
    requested_run_message_id = normalize_non_empty_string(run_message_id)
    effective_since_stream_event_id = max(0, since_stream_event_id)
    reconnect_wait_seconds = max(
        0.1,
        float(getattr(settings, "stream_reconnect_wait_seconds", 1.5) or 1.5),
    )

    if effective_since_stream_event_id > 0:
        meta = await get_stream_meta(conversation_id)
        if meta is None:
            log_event(
                logger,
                "INFO",
                "chat.ws.reconnect_waiting_for_stream_meta",
                "retry",
                conversation_id=conversation_id,
                user_id=user_id,
                requested_run_message_id=requested_run_message_id,
                since_stream_event_id=effective_since_stream_event_id,
                wait_seconds=reconnect_wait_seconds,
            )
            meta = await wait_for_stream_registration(
                conversation_id=conversation_id,
                user_id=user_id,
                timeout_seconds=reconnect_wait_seconds,
            )
    else:
        meta = await wait_for_stream_registration(
            conversation_id=conversation_id,
            user_id=user_id,
            timeout_seconds=float(settings.stream_connect_wait_seconds or 8.0),
        )

    active_run_message_id = meta.get("user_message_id") if isinstance(meta, dict) else None
    if (
        requested_run_message_id
        and isinstance(active_run_message_id, str)
        and active_run_message_id
        and requested_run_message_id != active_run_message_id
    ):
        log_event(
            logger,
            "INFO",
            "chat.ws.cursor_run_mismatch_reset",
            "retry",
            conversation_id=conversation_id,
            requested_run_message_id=requested_run_message_id,
            active_run_message_id=active_run_message_id,
            previous_since_stream_event_id=effective_since_stream_event_id,
            user_id=user_id,
        )
        effective_since_stream_event_id = 0

    if not meta:
        no_active_event_id = max(1, effective_since_stream_event_id + 1)
        await _send_push(
            state,
            channel=CHAT_WS_CHANNELS["stream_event"],
            data={
                "conversationId": conversation_id,
                "event": {
                    "id": no_active_event_id,
                    "type": "no_active_stream",
                    "data": {
                        "reason": "no_active_stream",
                        "conversationId": conversation_id,
                        "runMessageId": requested_run_message_id,
                    },
                },
            },
        )
        return

    try:
        async for event in subscribe_stream_events(
            conversation_id,
            effective_since_stream_event_id,
            user_id=user_id,
            requested_run_message_id=requested_run_message_id,
        ):
            payload = dict(event)
            await _send_push(
                state,
                channel=CHAT_WS_CHANNELS["stream_event"],
                data={
                    "conversationId": conversation_id,
                    "event": payload,
                },
            )
            if payload.get("type") in {"done", "error", "run.failed", "no_active_stream"}:
                return
    except asyncio.CancelledError:
        raise
    except WebSocketDisconnect:
        pass
    except _SOCKET_RESOURCE_CLOSED_EXCEPTIONS:
        pass
    except RuntimeError:
        pass
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.ws.stream_relay_failed",
            "retry",
            conversation_id=conversation_id,
            user_id=user_id,
            exc_info=True,
        )
        try:
            synthetic_error_id = max(1, effective_since_stream_event_id + 1)
            await _send_push(
                state,
                channel=CHAT_WS_CHANNELS["stream_event"],
                data={
                    "conversationId": conversation_id,
                    "event": {
                        "id": synthetic_error_id,
                        "type": "error",
                        "data": {
                            "message": "WebSocket stream relay failed",
                            "code": "WS_RELAY",
                        },
                    },
                },
            )
        except Exception:
            pass


async def _handle_request(
    state: _SocketState,
    body: ChatWsPingBody | ChatWsConversationRequestBody | ChatWsSubscribeStreamBody,
) -> Dict[str, Any]:
    method = body.tag

    if method == CHAT_WS_METHODS["ping"]:
        return {"ok": True}

    if not isinstance(body, (ChatWsConversationRequestBody, ChatWsSubscribeStreamBody)):
        raise ValueError(f"Unsupported method: {method}")

    conversation_id = body.conversation_id

    if method == CHAT_WS_METHODS["subscribe_stream"]:
        assert isinstance(body, ChatWsSubscribeStreamBody)
        await _require_websocket_conversation_access(state.user, conversation_id)
        await _cancel_stream_task(state, conversation_id)
        task = asyncio.create_task(
            _relay_conversation_stream(
                state,
                conversation_id=conversation_id,
                since_stream_event_id=body.since_stream_event_id,
                run_message_id=body.run_message_id,
            )
        )
        state.stream_tasks[conversation_id] = task
        return {
            "conversationId": conversation_id,
            "subscribed": True,
        }

    if method == CHAT_WS_METHODS["unsubscribe_stream"]:
        await _cancel_stream_task(state, conversation_id)
        return {
            "conversationId": conversation_id,
            "subscribed": False,
        }

    if method == CHAT_WS_METHODS["cancel_stream"]:
        return await cancel_conversation_stream(
            user=state.user,
            conversation_id=conversation_id,
            cancel_source="ws.cancel.no_active_stream",
            log_name="chat.ws.cancel_requested",
        )

    raise ValueError(f"Unsupported method: {method}")


@router.websocket("/ws")
async def chat_websocket(websocket: WebSocket) -> None:
    user = await _authenticate_websocket_user(websocket)
    if user is None:
        return

    await websocket.accept()
    state = _SocketState(websocket=websocket, user=user)
    user_id = str(user.id)
    log_event(
        logger,
        "INFO",
        "chat.ws.connected",
        "timing",
        user_id=user_id,
    )

    queue = subscribe_user(user_id)
    state.user_queue = queue
    state.user_task = asyncio.create_task(_relay_user_events(state, queue))

    try:
        await _send_initial_user_state(state)
        while True:
            raw_text = await websocket.receive_text()
            try:
                request = json.loads(raw_text)
            except json.JSONDecodeError:
                continue

            if not isinstance(request, dict):
                continue

            request_id = normalize_non_empty_string(request.get("id"))
            parsed_request = None
            try:
                parsed_request = parse_chat_ws_request(request)
            except Exception as exc:
                if request_id:
                    await _send_response(
                        state,
                        request_id=request_id,
                        error=_resolve_request_error_message(exc),
                    )
                continue

            try:
                result = await _handle_request(state, parsed_request.body)
                await _send_response(state, request_id=parsed_request.id, result=result)
            except Exception as exc:
                log_event(
                    logger,
                    "WARNING",
                    "chat.ws.request_failed",
                    "retry",
                    user_id=user_id,
                    method=getattr(parsed_request.body, "tag", None),
                    conversation_id=getattr(parsed_request.body, "conversation_id", None),
                    error_type=type(exc).__name__,
                )
                await _send_response(
                    state,
                    request_id=parsed_request.id,
                    error=_resolve_request_error_message(exc),
                )
    except WebSocketDisconnect:
        pass
    finally:
        if state.user_task is not None:
            state.user_task.cancel()
            await asyncio.gather(state.user_task, return_exceptions=True)
        if state.user_queue is not None:
            unsubscribe_user(user_id, state.user_queue)
        for conversation_id in list(state.stream_tasks):
            await _cancel_stream_task(state, conversation_id)
        log_event(
            logger,
            "INFO",
            "chat.ws.disconnected",
            "timing",
            user_id=user_id,
        )
