"""Provider registry and helper utilities for chat streaming.

This module centralizes provider-specific wiring so that the core
`ChatStreamingManager` can remain mostly provider-agnostic while this
open-source build stays OpenAI-only.
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Callable, Dict, List

from .openai_model import chat_stream as openai_chat_stream
from .tool_definitions import get_openai_tool_specs


ChatStreamer = Callable[..., AsyncGenerator[Dict[str, Any], None]]


def get_chat_streamer(provider_name: str) -> ChatStreamer:
    """Return the chat streaming coroutine for the given provider.

    The return value is a callable compatible with the shared OpenAI
    streaming adapter (query + history + tools + system prompt + model +
    tool_context, etc.).
    """
    normalized = (provider_name or "openai").strip().lower()

    if normalized == "openai":
        return openai_chat_stream

    # Fallback: default to the shared OpenAI adapter.
    return openai_chat_stream


def get_tool_specs_for_provider(
    provider_name: str,
    *,
    include_project_tools: bool,
    is_admin: bool,
) -> List[Dict[str, Any]]:
    """Return tool specifications for the given provider.

    Args:
        provider_name: AI provider name (openai)
        include_project_tools: Whether to include project-scoped tools
        is_admin: Whether the user has admin privileges
    """
    normalized = (provider_name or "openai").strip().lower()

    if normalized == "openai":
        return get_openai_tool_specs(
            include_project_tools=include_project_tools,
            is_admin=is_admin,
        )

    # Default: use OpenAI tool spec format.
    return get_openai_tool_specs(
        include_project_tools=include_project_tools,
        is_admin=is_admin,
    )


__all__ = [
    "ChatStreamer",
    "get_chat_streamer",
    "get_tool_specs_for_provider",
]
