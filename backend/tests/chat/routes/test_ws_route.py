from __future__ import annotations

import asyncio
from types import SimpleNamespace

import anyio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat.routes import ws


def _build_client(monkeypatch) -> TestClient:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.include_router(ws.router, prefix="/conversations")

    async def _fake_authenticate(_websocket):  # type: ignore[no-untyped-def]
        return SimpleNamespace(id="user-1", role="member", email="test@example.com")

    async def _fake_get_active_streams_for_user(_user_id: str):  # type: ignore[no-untyped-def]
        return [
            {
                "conversation_id": "conv_active",
                "user_message_id": "msg_1",
                "run_id": "run_1",
                "current_step": "Thinking",
            }
        ]

    async def _fake_require_access(_user, _conversation_id: str):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(ws, "_authenticate_websocket_user", _fake_authenticate)
    monkeypatch.setattr(ws, "get_active_streams_for_user", _fake_get_active_streams_for_user)
    monkeypatch.setattr(ws, "_require_websocket_conversation_access", _fake_require_access)
    monkeypatch.setattr(ws, "subscribe_user", lambda _user_id: asyncio.Queue())
    monkeypatch.setattr(ws, "unsubscribe_user", lambda _user_id, _queue: None)

    return TestClient(app, raise_server_exceptions=False)


def test_chat_websocket_sends_initial_user_state(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client(monkeypatch)

    with client.websocket_connect("/conversations/ws?token=test-token") as websocket:
        message = websocket.receive_json()

    assert message == {
        "type": "push",
        "channel": "chat.userEvent",
        "data": {
            "type": "initial_state",
            "streams": [
                {
                    "conversation_id": "conv_active",
                    "user_message_id": "msg_1",
                    "run_id": "run_1",
                    "current_step": "Thinking",
                }
            ],
        },
    }


def test_chat_websocket_subscribe_returns_ack_and_no_active_stream(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client(monkeypatch)

    async def _fake_wait_for_stream_registration(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(ws, "wait_for_stream_registration", _fake_wait_for_stream_registration)

    with client.websocket_connect("/conversations/ws?token=test-token") as websocket:
        websocket.receive_json()  # initial_state
        websocket.send_json(
            {
                "id": "1",
                "body": {
                    "_tag": "chat.stream.subscribe",
                    "conversationId": "conv_missing",
                    "sinceStreamEventId": 0,
                },
            }
        )

        response = websocket.receive_json()
        push = websocket.receive_json()

    assert response == {
        "id": "1",
        "result": {
            "conversationId": "conv_missing",
            "subscribed": True,
        },
    }
    assert push == {
        "type": "push",
        "channel": "chat.streamEvent",
        "data": {
            "conversationId": "conv_missing",
            "event": {
                "id": 1,
                "type": "no_active_stream",
                "data": {
                    "reason": "no_active_stream",
                    "conversationId": "conv_missing",
                    "runMessageId": None,
                },
            },
        },
    }


def test_chat_websocket_reconnect_waits_for_stream_meta_before_emitting_no_active(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client(monkeypatch)
    subscribe_calls = []

    async def _fake_get_stream_meta(_conversation_id: str):  # type: ignore[no-untyped-def]
        return None

    async def _fake_wait_for_stream_registration(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "user_id": "user-1",
            "user_message_id": "msg_1",
            "run_id": "run_1",
            "status": "running",
        }

    async def _fake_subscribe_stream_events(conversation_id, since_stream_event_id, **kwargs):  # type: ignore[no-untyped-def]
        subscribe_calls.append((conversation_id, since_stream_event_id, kwargs))
        yield {
            "id": 6,
            "type": "content.delta",
            "data": {
                "delta": "Hello",
                "runMessageId": "msg_1",
            },
        }

    monkeypatch.setattr(ws, "get_stream_meta", _fake_get_stream_meta)
    monkeypatch.setattr(ws, "wait_for_stream_registration", _fake_wait_for_stream_registration)
    monkeypatch.setattr(ws, "subscribe_stream_events", _fake_subscribe_stream_events)

    with client.websocket_connect("/conversations/ws?token=test-token") as websocket:
        websocket.receive_json()  # initial_state
        websocket.send_json(
            {
                "id": "3",
                "body": {
                    "_tag": "chat.stream.subscribe",
                    "conversationId": "conv_reconnect",
                    "sinceStreamEventId": 5,
                    "runMessageId": "msg_1",
                },
            }
        )

        response = websocket.receive_json()
        push = websocket.receive_json()

    assert response == {
        "id": "3",
        "result": {
            "conversationId": "conv_reconnect",
            "subscribed": True,
        },
    }
    assert push == {
        "type": "push",
        "channel": "chat.streamEvent",
        "data": {
            "conversationId": "conv_reconnect",
            "event": {
                "id": 6,
                "type": "content.delta",
                "data": {
                    "delta": "Hello",
                    "runMessageId": "msg_1",
                },
            },
        },
    }
    assert subscribe_calls == [
        (
            "conv_reconnect",
            5,
            {
                "user_id": "user-1",
                "requested_run_message_id": "msg_1",
            },
        )
    ]


def test_chat_websocket_shared_conversation_reconnect_uses_owner_stream_meta(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client(monkeypatch)
    subscribe_calls = []

    async def _fake_get_stream_meta(_conversation_id: str):  # type: ignore[no-untyped-def]
        return {
            "user_id": "owner-user",
            "user_message_id": "msg_owner",
            "run_id": "run_owner",
            "status": "running",
        }

    async def _fake_subscribe_stream_events(conversation_id, since_stream_event_id, **kwargs):  # type: ignore[no-untyped-def]
        subscribe_calls.append((conversation_id, since_stream_event_id, kwargs))
        yield {
            "id": 8,
            "type": "content.delta",
            "data": {
                "delta": "Shared update",
                "runMessageId": "msg_owner",
            },
        }

    monkeypatch.setattr(ws, "get_stream_meta", _fake_get_stream_meta)
    monkeypatch.setattr(ws, "subscribe_stream_events", _fake_subscribe_stream_events)

    with client.websocket_connect("/conversations/ws?token=test-token") as websocket:
        websocket.receive_json()  # initial_state
        websocket.send_json(
            {
                "id": "shared-1",
                "body": {
                    "_tag": "chat.stream.subscribe",
                    "conversationId": "conv_shared",
                    "sinceStreamEventId": 7,
                    "runMessageId": "msg_owner",
                },
            }
        )

        response = websocket.receive_json()
        push = websocket.receive_json()

    assert response == {
        "id": "shared-1",
        "result": {
            "conversationId": "conv_shared",
            "subscribed": True,
        },
    }
    assert push == {
        "type": "push",
        "channel": "chat.streamEvent",
        "data": {
            "conversationId": "conv_shared",
            "event": {
                "id": 8,
                "type": "content.delta",
                "data": {
                    "delta": "Shared update",
                    "runMessageId": "msg_owner",
                },
            },
        },
    }
    assert subscribe_calls == [
        (
            "conv_shared",
            7,
            {
                "user_id": "user-1",
                "requested_run_message_id": "msg_owner",
            },
        )
    ]


def test_chat_websocket_cancel_delegates_to_cancel_service(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client(monkeypatch)
    captured = {}

    async def _fake_cancel_conversation_stream(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"status": "cancelled", "persisted": False}

    monkeypatch.setattr(ws, "cancel_conversation_stream", _fake_cancel_conversation_stream)

    with client.websocket_connect("/conversations/ws?token=test-token") as websocket:
        websocket.receive_json()  # initial_state
        websocket.send_json(
            {
                "id": "2",
                "body": {
                    "_tag": "chat.stream.cancel",
                    "conversationId": "conv_running",
                },
            }
        )
        response = websocket.receive_json()

    assert captured == {
        "user": SimpleNamespace(id="user-1", role="member", email="test@example.com"),
        "conversation_id": "conv_running",
        "cancel_source": "ws.cancel.no_active_stream",
        "log_name": "chat.ws.cancel_requested",
    }
    assert response == {
        "id": "2",
        "result": {
            "status": "cancelled",
            "persisted": False,
        },
    }


def test_websocket_conversation_access_uses_shared_conversation_guard(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured = {}

    async def _fake_require_accessible_conversation_async(db, *, current_user, conversation_id):  # type: ignore[no-untyped-def]
        captured["db"] = db
        captured["current_user"] = current_user
        captured["conversation_id"] = conversation_id
        return None

    monkeypatch.setattr(ws, "require_accessible_conversation_async", _fake_require_accessible_conversation_async)

    user = SimpleNamespace(id="user-2", role="member", email="member@example.com")

    asyncio.run(ws._require_websocket_conversation_access(user, "conv_shared"))

    assert captured["conversation_id"] == "conv_shared"
    assert captured["current_user"] == user


def test_chat_websocket_sanitizes_unexpected_request_errors(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client(monkeypatch)

    async def _raise_internal_error(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("database timeout: secret stack detail")

    monkeypatch.setattr(ws, "_handle_request", _raise_internal_error)

    with client.websocket_connect("/conversations/ws?token=test-token") as websocket:
        websocket.receive_json()  # initial_state
        websocket.send_json(
            {
                "id": "err-1",
                "body": {
                    "_tag": "chat.stream.subscribe",
                    "conversationId": "conv_missing",
                },
            }
        )
        response = websocket.receive_json()

    assert response == {
        "id": "err-1",
        "error": {
            "message": "Request failed",
        },
    }


def test_chat_websocket_preserves_validation_error_messages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = _build_client(monkeypatch)

    async def _raise_validation_error(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("conversationId is required")

    monkeypatch.setattr(ws, "_handle_request", _raise_validation_error)

    with client.websocket_connect("/conversations/ws?token=test-token") as websocket:
        websocket.receive_json()  # initial_state
        websocket.send_json(
            {
                "id": "err-2",
                "body": {
                    "_tag": "chat.stream.subscribe",
                    "conversationId": "conv_missing",
                },
            }
        )
        response = websocket.receive_json()

    assert response == {
        "id": "err-2",
        "error": {
            "message": "conversationId is required",
        },
    }


def test_relay_conversation_stream_treats_closed_socket_resources_as_disconnect(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state = ws._SocketState(
        websocket=SimpleNamespace(),
        user=SimpleNamespace(id="user-1", role="member", email="test@example.com"),
    )
    send_attempts = 0

    async def _fake_wait_for_stream_registration(*args, **kwargs):  # type: ignore[no-untyped-def]
        return {
            "user_id": "user-1",
            "user_message_id": "msg_1",
            "run_id": "run_1",
            "status": "running",
        }

    async def _fake_subscribe_stream_events(*args, **kwargs):  # type: ignore[no-untyped-def]
        yield {
            "id": 1,
            "type": "content.delta",
            "data": {
                "delta": "Hello",
                "runMessageId": "msg_1",
            },
        }

    async def _fake_send_push(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal send_attempts
        send_attempts += 1
        raise anyio.BrokenResourceError

    monkeypatch.setattr(ws, "wait_for_stream_registration", _fake_wait_for_stream_registration)
    monkeypatch.setattr(ws, "subscribe_stream_events", _fake_subscribe_stream_events)
    monkeypatch.setattr(ws, "_send_push", _fake_send_push)

    asyncio.run(
        ws._relay_conversation_stream(
            state,
            conversation_id="conv_1",
            since_stream_event_id=0,
            run_message_id="msg_1",
        )
    )

    assert send_attempts == 1
