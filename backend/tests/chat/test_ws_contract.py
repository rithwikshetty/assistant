from __future__ import annotations

import pytest

from app.chat.ws_contract import (
    CHAT_WS_CHANNELS,
    CHAT_WS_METHODS,
    build_chat_ws_push,
    build_chat_ws_response,
    export_chat_ws_contract_manifest,
    parse_chat_user_event_data,
    parse_chat_ws_request,
    validate_chat_stream_push_payload,
    validate_chat_user_event_payload,
    validate_chat_ws_manifest,
)


def test_parse_chat_ws_subscribe_request_normalizes_payload() -> None:
    parsed = parse_chat_ws_request(
        {
            "id": "req_1",
            "body": {
                "_tag": CHAT_WS_METHODS["subscribe_stream"],
                "conversationId": "conv_1",
                "sinceStreamEventId": "4",
                "runMessageId": "msg_1",
            },
        }
    )

    assert parsed.id == "req_1"
    assert parsed.body.tag == CHAT_WS_METHODS["subscribe_stream"]
    assert parsed.body.conversation_id == "conv_1"
    assert parsed.body.since_stream_event_id == 4
    assert parsed.body.run_message_id == "msg_1"


def test_parse_chat_ws_request_rejects_unknown_method() -> None:
    with pytest.raises(ValueError, match="Unsupported method"):
        parse_chat_ws_request(
            {
                "id": "req_1",
                "body": {
                    "_tag": "chat.stream.unknown",
                },
            }
        )


def test_build_chat_ws_envelopes_use_canonical_shape() -> None:
    response = build_chat_ws_response(request_id="req_2", result={"ok": True})
    assert response == {"id": "req_2", "result": {"ok": True}}

    push = build_chat_ws_push(
        channel=CHAT_WS_CHANNELS["user_event"],
        data={"type": "initial_state", "streams": []},
    )
    assert push == {
        "type": "push",
        "channel": CHAT_WS_CHANNELS["user_event"],
        "data": {"type": "initial_state", "streams": []},
    }


def test_chat_ws_manifest_is_valid_and_includes_interactive_tools() -> None:
    validate_chat_ws_manifest()
    manifest = export_chat_ws_contract_manifest()

    assert "request_user_input" in manifest["tool_names"]
    assert manifest["interactive_tool_names"] == ["request_user_input"]
    assert "stream_registered" not in manifest["user_event_types"]


def test_validate_chat_user_event_payload_rejects_internal_registration_events() -> None:
    with pytest.raises(ValueError, match="unsupported chat user event type"):
        validate_chat_user_event_payload(
            {
                "type": "stream_registered",
                "conversation_id": "conv_1",
            }
        )


def test_build_chat_ws_push_validates_stream_and_user_payloads() -> None:
    user_push = build_chat_ws_push(
        channel=CHAT_WS_CHANNELS["user_event"],
        data={
            "type": "conversation_title_updated",
            "conversation_id": "conv_1",
            "title": "New title",
            "updated_at": "2026-03-13T00:00:00Z",
        },
    )
    assert user_push == {
        "type": "push",
        "channel": CHAT_WS_CHANNELS["user_event"],
        "data": {
            "type": "conversation_title_updated",
            "conversation_id": "conv_1",
            "title": "New title",
            "updated_at": "2026-03-13T00:00:00Z",
        },
    }

    stream_push = build_chat_ws_push(
        channel=CHAT_WS_CHANNELS["stream_event"],
        data={
            "conversationId": "conv_1",
            "event": {
                "id": 5,
                "type": "runtime_update",
                "data": {"statusLabel": "Thinking"},
            },
        },
    )
    assert stream_push == {
        "type": "push",
        "channel": CHAT_WS_CHANNELS["stream_event"],
        "data": {
            "conversationId": "conv_1",
            "event": {
                "id": 5,
                "type": "runtime_update",
                "data": {"statusLabel": "Thinking"},
            },
        },
    }


def test_validate_chat_stream_push_payload_rejects_invalid_event_type() -> None:
    with pytest.raises(ValueError, match="unsupported chat stream event type"):
        validate_chat_stream_push_payload(
            {
                "conversationId": "conv_1",
                "event": {
                    "id": 5,
                    "type": "stream_registered",
                    "data": {},
                },
            }
        )


def test_parse_chat_user_event_data_normalizes_initial_state_streams() -> None:
    parsed = parse_chat_user_event_data(
        {
            "type": "initial_state",
            "streams": [
                {
                    "conversation_id": "conv_1",
                    "user_message_id": "msg_1",
                    "run_id": "run_1",
                    "started_at": "2026-03-13T00:00:00Z",
                    "current_step": "Thinking",
                }
            ],
        }
    )

    assert parsed.type == "initial_state"
    assert len(parsed.streams) == 1
    assert parsed.streams[0].conversation_id == "conv_1"
