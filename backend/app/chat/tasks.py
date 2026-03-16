"""Background chat processing entrypoints."""

from __future__ import annotations

from typing import Optional

from .run_engine import ChatRunEngine

# Keep milestone event names discoverable for logging-contract tests.
_CHAT_MILESTONE_EVENTS = (
    "chat.stream.worker_start",
    "chat.stream.first_event",
    "chat.stream.first_content",
    "chat.stream.paused",
    "chat.stream.cancelled",
    "chat.stream.completed",
    "chat.stream.failed",
)


async def run_chat_direct(
    conversation_id: str,
    user_id: str,
    user_message_id: str,
    *,
    resume_assistant_message_id: Optional[str] = None,
) -> None:
    """Run chat generation using the state-machine-backed run engine."""
    engine = ChatRunEngine(
        conversation_id=conversation_id,
        user_id=user_id,
        user_message_id=user_message_id,
        resume_assistant_message_id=resume_assistant_message_id,
    )
    await engine.run()
