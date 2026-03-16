"""Canonical chat websocket contract definitions.

This module is the backend-owned source of truth for:
- websocket method names
- websocket push channels
- stream event type names
- user lifecycle event type names
- canonical backend tool-name vocabulary used by chat/runtime payloads

It intentionally stays lightweight. The goal is authority and exportability,
not introducing a second protocol framework.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .interactive_tools import INTERACTIVE_TOOL_NAMES
from .tool_definitions import list_all_tool_names


CHAT_WS_CHANNELS: Dict[str, str] = {
    "user_event": "chat.userEvent",
    "stream_event": "chat.streamEvent",
}

CHAT_WS_METHODS: Dict[str, str] = {
    "subscribe_stream": "chat.stream.subscribe",
    "unsubscribe_stream": "chat.stream.unsubscribe",
    "cancel_stream": "chat.stream.cancel",
    "ping": "chat.ping",
}

CHAT_STREAM_EVENT_TYPES: tuple[str, ...] = (
    "replay_gap",
    "no_active_stream",
    "run.status",
    "runtime_update",
    "content.delta",
    "content.done",
    "tool.started",
    "tool.progress",
    "tool.completed",
    "tool.failed",
    "input.requested",
    "error",
    "run.failed",
    "done",
    "conversation_usage",
)

CHAT_USER_EVENT_TYPES: tuple[str, ...] = (
    "initial_state",
    "stream_started",
    "stream_resumed",
    "stream_paused",
    "stream_completed",
    "stream_failed",
    "conversation_title_updated",
)


def list_chat_tool_names() -> List[str]:
    return list_all_tool_names()


def list_interactive_chat_tool_names() -> List[str]:
    return sorted(INTERACTIVE_TOOL_NAMES)


def _normalize_non_empty_string(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("must be a string")
    normalized = raw.strip()
    if not normalized:
        raise ValueError("must not be empty")
    return normalized


def _normalize_non_negative_int(raw: Any, *, default: int = 0) -> int:
    if raw is None:
        return default
    if isinstance(raw, bool):
        raise ValueError("must be a non-negative integer")
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, float) and raw.is_integer():
        return max(0, int(raw))
    if isinstance(raw, str) and raw.strip():
        try:
            return max(0, int(raw.strip()))
        except ValueError as exc:
            raise ValueError("must be a non-negative integer") from exc
    raise ValueError("must be a non-negative integer")


class ChatWsEnvelopeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatWsRequestBodyBase(ChatWsEnvelopeBase):
    tag: str = Field(alias="_tag")

    @field_validator("tag")
    @classmethod
    def validate_tag(cls, value: str) -> str:
        return _normalize_non_empty_string(value)


class ChatWsSubscribeStreamBody(ChatWsRequestBodyBase):
    conversation_id: str = Field(alias="conversationId")
    since_stream_event_id: int = Field(default=0, alias="sinceStreamEventId")
    run_message_id: Optional[str] = Field(default=None, alias="runMessageId")

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        return _normalize_non_empty_string(value)

    @field_validator("since_stream_event_id", mode="before")
    @classmethod
    def validate_since_stream_event_id(cls, value: Any) -> int:
        return _normalize_non_negative_int(value, default=0)

    @field_validator("run_message_id")
    @classmethod
    def validate_run_message_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_non_empty_string(value)


class ChatWsConversationRequestBody(ChatWsRequestBodyBase):
    conversation_id: str = Field(alias="conversationId")

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        return _normalize_non_empty_string(value)


class ChatWsPingBody(ChatWsRequestBodyBase):
    pass


class ChatWsRequestEnvelope(ChatWsEnvelopeBase):
    id: str
    body: Dict[str, Any]

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _normalize_non_empty_string(value)


class ParsedChatWsRequest(ChatWsEnvelopeBase):
    id: str
    body: ChatWsRequestBodyBase


class ChatWsErrorPayload(ChatWsEnvelopeBase):
    message: str


class ChatWsResponseEnvelope(ChatWsEnvelopeBase):
    id: str
    result: Optional[Any] = None
    error: Optional[ChatWsErrorPayload] = None


class ChatWsPushEnvelope(ChatWsEnvelopeBase):
    type: str
    channel: str
    data: Any

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        normalized = _normalize_non_empty_string(value)
        if normalized != "push":
            raise ValueError("type must be push")
        return normalized

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, value: str) -> str:
        normalized = _normalize_non_empty_string(value)
        if normalized not in CHAT_WS_CHANNELS.values():
            raise ValueError("unsupported chat websocket channel")
        return normalized


class ChatWsUserActiveStream(ChatWsEnvelopeBase):
    conversation_id: str
    user_message_id: Optional[str] = None
    run_id: Optional[str] = None
    started_at: Optional[str] = None
    current_step: Optional[str] = None

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        return _normalize_non_empty_string(value)

    @field_validator("user_message_id", "run_id", "started_at", "current_step")
    @classmethod
    def validate_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_non_empty_string(value)


class ChatWsInitialStateUserEvent(ChatWsEnvelopeBase):
    type: Literal["initial_state"]
    streams: List[ChatWsUserActiveStream] = Field(default_factory=list)


class ChatWsStreamLifecycleUserEvent(ChatWsEnvelopeBase):
    type: Literal["stream_started", "stream_resumed", "stream_paused", "stream_completed", "stream_failed"]
    conversation_id: str
    user_message_id: Optional[str] = None
    run_id: Optional[str] = None
    status: Optional[str] = None
    current_step: Optional[str] = None
    started_at: Optional[str] = None

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        return _normalize_non_empty_string(value)

    @field_validator("user_message_id", "run_id", "status", "current_step", "started_at")
    @classmethod
    def validate_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_non_empty_string(value)


class ChatWsConversationTitleUpdatedUserEvent(ChatWsEnvelopeBase):
    type: Literal["conversation_title_updated"]
    conversation_id: str
    title: str
    updated_at: Optional[str] = None
    source: Optional[str] = None

    @field_validator("conversation_id", "title")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _normalize_non_empty_string(value)

    @field_validator("updated_at", "source")
    @classmethod
    def validate_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_non_empty_string(value)


class ChatWsStreamEventPayload(ChatWsEnvelopeBase):
    id: int
    type: str
    data: Any = None

    @field_validator("id", mode="before")
    @classmethod
    def validate_id(cls, value: Any) -> int:
        if value is None:
            raise ValueError("chat stream event id is required")
        return _normalize_non_negative_int(value, default=0)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        normalized = _normalize_non_empty_string(value)
        if normalized not in CHAT_STREAM_EVENT_TYPES:
            raise ValueError("unsupported chat stream event type")
        return normalized


class ChatWsStreamPushData(ChatWsEnvelopeBase):
    conversation_id: str = Field(alias="conversationId")
    event: ChatWsStreamEventPayload

    @field_validator("conversation_id")
    @classmethod
    def validate_conversation_id(cls, value: str) -> str:
        return _normalize_non_empty_string(value)


ChatWsUserEventData = (
    ChatWsInitialStateUserEvent
    | ChatWsStreamLifecycleUserEvent
    | ChatWsConversationTitleUpdatedUserEvent
)


def parse_chat_user_event_data(raw: Any) -> ChatWsUserEventData:
    if not isinstance(raw, dict):
        raise ValueError("chat user event payload must be an object")
    event_type = _normalize_non_empty_string(raw.get("type"))
    if event_type == "initial_state":
        return ChatWsInitialStateUserEvent.model_validate(raw)
    if event_type in {"stream_started", "stream_resumed", "stream_paused", "stream_completed", "stream_failed"}:
        return ChatWsStreamLifecycleUserEvent.model_validate(raw)
    if event_type == "conversation_title_updated":
        return ChatWsConversationTitleUpdatedUserEvent.model_validate(raw)
    raise ValueError("unsupported chat user event type")


def validate_chat_user_event_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    return parse_chat_user_event_data(raw).model_dump(mode="json", exclude_none=True)


def validate_chat_stream_push_payload(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("chat stream push payload must be an object")

    conversation_id = _normalize_non_empty_string(raw.get("conversationId"))
    raw_event = raw.get("event")
    if not isinstance(raw_event, dict):
        raise ValueError("chat stream push payload.event must be an object")
    if raw_event.get("id") is None:
        raise ValueError("chat stream event id is required")

    event_id = _normalize_non_negative_int(raw_event.get("id"), default=0)
    event_type = _normalize_non_empty_string(raw_event.get("type"))
    if event_type not in CHAT_STREAM_EVENT_TYPES:
        raise ValueError("unsupported chat stream event type")

    normalized_event = dict(raw_event)
    normalized_event["id"] = event_id
    normalized_event["type"] = event_type

    normalized_payload = dict(raw)
    normalized_payload["conversationId"] = conversation_id
    normalized_payload["event"] = normalized_event
    return normalized_payload


def parse_chat_ws_request(raw_request: Dict[str, Any]) -> ParsedChatWsRequest:
    envelope = ChatWsRequestEnvelope.model_validate(raw_request)
    raw_body = envelope.body
    method = _normalize_non_empty_string(raw_body.get("_tag"))

    if method == CHAT_WS_METHODS["subscribe_stream"]:
        body = ChatWsSubscribeStreamBody.model_validate(raw_body)
    elif method == CHAT_WS_METHODS["unsubscribe_stream"]:
        body = ChatWsConversationRequestBody.model_validate(raw_body)
    elif method == CHAT_WS_METHODS["cancel_stream"]:
        body = ChatWsConversationRequestBody.model_validate(raw_body)
    elif method == CHAT_WS_METHODS["ping"]:
        body = ChatWsPingBody.model_validate(raw_body)
    else:
        raise ValueError(f"Unsupported method: {method}")

    return ParsedChatWsRequest(id=envelope.id, body=body)


def build_chat_ws_response(*, request_id: str, result: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    normalized_request_id = _normalize_non_empty_string(request_id)
    if error:
        envelope = ChatWsResponseEnvelope(
            id=normalized_request_id,
            error=ChatWsErrorPayload(message=_normalize_non_empty_string(error)),
        )
    else:
        envelope = ChatWsResponseEnvelope(id=normalized_request_id, result=result)
    return envelope.model_dump(mode="json", by_alias=True, exclude_none=True)


def build_chat_ws_push(*, channel: str, data: Any) -> Dict[str, Any]:
    normalized_channel = _normalize_non_empty_string(channel) if isinstance(channel, str) else ""
    if normalized_channel not in CHAT_WS_CHANNELS.values():
        raise ValueError("unsupported chat websocket channel")

    if normalized_channel == CHAT_WS_CHANNELS["user_event"]:
        normalized_data = validate_chat_user_event_payload(data if isinstance(data, dict) else {})
    else:
        normalized_data = validate_chat_stream_push_payload(data)

    return {"type": "push", "channel": normalized_channel, "data": normalized_data}


def export_chat_ws_contract_manifest() -> Dict[str, Any]:
    return {
        "channels": CHAT_WS_CHANNELS,
        "methods": CHAT_WS_METHODS,
        "stream_event_types": list(CHAT_STREAM_EVENT_TYPES),
        "user_event_types": list(CHAT_USER_EVENT_TYPES),
        "tool_names": list_chat_tool_names(),
        "interactive_tool_names": list_interactive_chat_tool_names(),
    }


def validate_chat_ws_manifest() -> None:
    tool_names = list_chat_tool_names()
    if not tool_names:
        raise ValueError("chat websocket manifest cannot be empty")
    if len(tool_names) != len(set(tool_names)):
        raise ValueError("chat tool names must be unique")
    interactive_tool_names = list_interactive_chat_tool_names()
    if not set(interactive_tool_names).issubset(tool_names):
        raise ValueError("interactive chat tool names must be a subset of tool names")
    if len(CHAT_STREAM_EVENT_TYPES) != len(set(CHAT_STREAM_EVENT_TYPES)):
        raise ValueError("chat stream event types must be unique")
    if len(CHAT_USER_EVENT_TYPES) != len(set(CHAT_USER_EVENT_TYPES)):
        raise ValueError("chat user event types must be unique")


__all__ = [
    "CHAT_STREAM_EVENT_TYPES",
    "CHAT_USER_EVENT_TYPES",
    "CHAT_WS_CHANNELS",
    "CHAT_WS_METHODS",
    "ChatWsConversationTitleUpdatedUserEvent",
    "ChatWsConversationRequestBody",
    "ChatWsInitialStateUserEvent",
    "ChatWsPingBody",
    "ChatWsRequestEnvelope",
    "ChatWsStreamLifecycleUserEvent",
    "ChatWsSubscribeStreamBody",
    "build_chat_ws_push",
    "build_chat_ws_response",
    "export_chat_ws_contract_manifest",
    "list_chat_tool_names",
    "list_interactive_chat_tool_names",
    "parse_chat_user_event_data",
    "parse_chat_ws_request",
    "validate_chat_stream_push_payload",
    "validate_chat_user_event_payload",
    "validate_chat_ws_manifest",
]
