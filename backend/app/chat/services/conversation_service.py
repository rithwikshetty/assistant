"""Conversation business logic and helper functions."""
from datetime import datetime, timezone
from typing import Tuple, Optional, Any, Dict
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from ...database.models import (
    Conversation,
    Message,
    ConversationState,
    MessageFeedback,
    User,
)
from ...config.settings import settings
from ..schemas import ConversationResponse
from ..title_generator import generate_title
from ...utils.coerce import coerce_int
from ...utils.datetime_helpers import format_utc_z
from ...services.chat_streams import publish_user_event


FEEDBACK_MESSAGES_INTERVAL = 5
FEEDBACK_METADATA_KEY = "feedback"
FEEDBACK_METADATA_VERSION = 1
FEEDBACK_METADATA_MESSAGES_PER_CYCLE_KEY = "messages_per_cycle"


async def publish_conversation_title_updated(
    conversation: Conversation,
    *,
    source: str,
) -> None:
    user_id = getattr(conversation, "user_id", None)
    if not user_id:
        return
    await publish_user_event(str(user_id), {
        "type": "conversation_title_updated",
        "conversation_id": str(conversation.id),
        "title": str(conversation.title or "").strip(),
        "updated_at": format_utc_z(getattr(conversation, "updated_at", None)),
        "source": source,
    })


def _coerce_non_negative(value: Any) -> Optional[int]:
    coerced = coerce_int(value)
    if coerced is None:
        return None
    return coerced if coerced >= 0 else None


def _resolve_effective_message_count(
    conversation: Conversation,
    own_message_count: int,
) -> int:
    """Return canonical message count for this conversation."""
    _ = conversation
    return max(0, int(own_message_count))


def _build_context_usage_from_state(
    state: Optional[ConversationState],
) -> Optional[Dict[str, int]]:
    if state is None:
        return None

    input_tokens = _coerce_non_negative(getattr(state, "input_tokens", None))
    output_tokens = _coerce_non_negative(getattr(state, "output_tokens", None))
    total_tokens = _coerce_non_negative(getattr(state, "total_tokens", None))
    max_context_tokens = _coerce_non_negative(getattr(state, "max_context_tokens", None))
    remaining_context_tokens = _coerce_non_negative(getattr(state, "remaining_context_tokens", None))
    cumulative_input_tokens = _coerce_non_negative(getattr(state, "cumulative_input_tokens", None))
    cumulative_output_tokens = _coerce_non_negative(getattr(state, "cumulative_output_tokens", None))
    cumulative_total_tokens = _coerce_non_negative(getattr(state, "cumulative_total_tokens", None))

    has_persisted_usage = any(
        value is not None
        for value in (
            input_tokens,
            output_tokens,
            total_tokens,
            max_context_tokens,
            remaining_context_tokens,
            cumulative_input_tokens,
            cumulative_output_tokens,
            cumulative_total_tokens,
        )
    )
    if not has_persisted_usage:
        return None

    usage: Dict[str, int] = {}
    if input_tokens is not None:
        usage["input_tokens"] = input_tokens
    if output_tokens is not None:
        usage["output_tokens"] = output_tokens
    if total_tokens is not None:
        usage["total_tokens"] = total_tokens
    if max_context_tokens is not None:
        usage["max_context_tokens"] = max_context_tokens
    if remaining_context_tokens is not None:
        usage["remaining_context_tokens"] = remaining_context_tokens
    if cumulative_input_tokens is not None:
        usage["cumulative_input_tokens"] = cumulative_input_tokens
    if cumulative_output_tokens is not None:
        usage["cumulative_output_tokens"] = cumulative_output_tokens
    if cumulative_total_tokens is not None:
        usage["cumulative_total_tokens"] = cumulative_total_tokens

    current_context_tokens: Optional[int] = None
    if max_context_tokens is not None and remaining_context_tokens is not None:
        # Prefer reconstructing "current context" from window occupancy so we
        # stay accurate even when input/total are max-aggregated across turns.
        reconstructed_current = max_context_tokens - remaining_context_tokens
        current_context_tokens = max(0, min(max_context_tokens, reconstructed_current))
    elif total_tokens is not None:
        current_context_tokens = total_tokens
    else:
        current_context_tokens = input_tokens

    if current_context_tokens is not None:
        if max_context_tokens is not None:
            current_context_tokens = max(0, min(max_context_tokens, current_context_tokens))
        usage["current_context_tokens"] = current_context_tokens

    peak_candidates = [
        value
        for value in (input_tokens, total_tokens, current_context_tokens)
        if value is not None
    ]
    if peak_candidates:
        peak_context_tokens = max(peak_candidates)
        if max_context_tokens is not None:
            peak_context_tokens = min(max_context_tokens, peak_context_tokens)
        usage["peak_context_tokens"] = peak_context_tokens

    compact_trigger_tokens = _coerce_non_negative(getattr(settings, "openai_compact_trigger_tokens", None))
    if compact_trigger_tokens is not None and compact_trigger_tokens > 0:
        usage["compact_trigger_tokens"] = compact_trigger_tokens

    return usage


def _compute_feedback_requirement(
    assistant_message_count: int,
    feedback_count: int,
    interval: int,
) -> bool:
    if interval <= 0:
        interval = FEEDBACK_MESSAGES_INTERVAL
    if assistant_message_count <= 0:
        return False

    current_cycle = assistant_message_count // interval
    return current_cycle > max(feedback_count, 0)


def requires_feedback_from_metadata(
    metadata: Any,
    feedback_count: int,
    assistant_message_count: Optional[int] = None,
) -> bool:
    """Determine if a conversation requires feedback using raw metadata and assistant counts."""
    if assistant_message_count is None or assistant_message_count <= 0:
        return False

    interval = FEEDBACK_MESSAGES_INTERVAL
    if isinstance(metadata, dict):
        feedback_meta = metadata.get(FEEDBACK_METADATA_KEY)
        if isinstance(feedback_meta, dict):
            resolved_interval = _coerce_non_negative(feedback_meta.get(FEEDBACK_METADATA_MESSAGES_PER_CYCLE_KEY))
            if resolved_interval and resolved_interval > 0:
                interval = resolved_interval

    return _compute_feedback_requirement(
        assistant_message_count=assistant_message_count,
        feedback_count=feedback_count,
        interval=interval,
    )


def check_requires_feedback(
    conversation: Conversation,
    db: Session,
    feedback_count: Optional[int] = None,
    assistant_message_count: Optional[int] = None,
) -> bool:
    """Check if conversation requires feedback before allowing new messages.

    Args:
        conversation: Conversation model instance
        db: Database session
        feedback_count: Optional precomputed feedback count for the conversation
        assistant_message_count: Optional precomputed count of assistant messages

    Returns:
        True if feedback is required, False otherwise
    """
    resolved_assistant_count: Optional[int] = assistant_message_count
    if resolved_assistant_count is None:
        resolved_assistant_count = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
                Message.status.in_(("completed", "failed", "cancelled")),
            )
            .count()
        )

    interval = FEEDBACK_MESSAGES_INTERVAL
    metadata = conversation.conversation_metadata
    if isinstance(metadata, dict):
        feedback_meta = metadata.get(FEEDBACK_METADATA_KEY)
        if isinstance(feedback_meta, dict):
            resolved_interval = _coerce_non_negative(
                feedback_meta.get(FEEDBACK_METADATA_MESSAGES_PER_CYCLE_KEY)
            )
            if resolved_interval and resolved_interval > 0:
                interval = resolved_interval

    if resolved_assistant_count is None or resolved_assistant_count < interval:
        return False

    resolved_feedback_count: Optional[int] = feedback_count
    if resolved_feedback_count is None:
        resolved_feedback_count = (
            db.query(MessageFeedback)
            .join(Message, MessageFeedback.message_id == Message.id)
            .filter(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
                Message.status.in_(("completed", "failed", "cancelled")),
            )
            .count()
        )

    return _compute_feedback_requirement(
        assistant_message_count=resolved_assistant_count,
        feedback_count=resolved_feedback_count or 0,
        interval=interval,
    )


async def ensure_conversation_title(
    conversation: Conversation,
    db: Session,
) -> Tuple[str, bool]:
    """Return an existing custom title or generate and persist a new one.

    Args:
        conversation: Conversation model instance
        db: Database session

    Returns:
        Tuple of (title, was_generated)

    Raises:
        HTTPException: If no user messages found for title generation
    """
    current_title = (conversation.title or "").strip()
    if current_title and current_title != "New Chat":
        return current_title, False

    first_user_event = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.role == "user",
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .first()
    )

    if not first_user_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user messages found in conversation",
        )

    first_user_text = first_user_event.text if isinstance(first_user_event.text, str) else None
    if not isinstance(first_user_text, str) or not first_user_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user messages found in conversation",
        )

    generated_title = await generate_title(
        first_user_text,
        analytics_context={
            "db": db,
            "user_id": str(conversation.user_id) if conversation.user_id else None,
            "conversation_id": str(conversation.id),
            "project_id": str(conversation.project_id) if conversation.project_id else None,
        },
    )
    cleaned_title = generated_title.strip() if isinstance(generated_title, str) else ""
    if not cleaned_title:
        cleaned_title = "New Chat"

    if cleaned_title == (conversation.title or ""):
        return cleaned_title, False

    conversation.title = cleaned_title
    db.commit()
    db.refresh(conversation)
    await publish_conversation_title_updated(conversation, source="generated")
    return conversation.title, True


async def ensure_conversation_title_async(
    conversation: Conversation,
    db: AsyncSession,
) -> Tuple[str, bool]:
    """Async variant of title generation for async route paths."""
    current_title = (conversation.title or "").strip()
    if current_title and current_title != "New Chat":
        return current_title, False

    first_user_event = await db.scalar(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.role == "user",
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(1)
    )

    if not first_user_event:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user messages found in conversation",
        )

    first_user_text = first_user_event.text if isinstance(first_user_event.text, str) else None
    if not isinstance(first_user_text, str) or not first_user_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user messages found in conversation",
        )

    generated_title = await generate_title(
        first_user_text,
        analytics_context={
            "user_id": str(conversation.user_id) if conversation.user_id else None,
            "conversation_id": str(conversation.id),
            "project_id": str(conversation.project_id) if conversation.project_id else None,
        },
    )
    cleaned_title = generated_title.strip() if isinstance(generated_title, str) else ""
    if not cleaned_title:
        cleaned_title = "New Chat"

    if cleaned_title == (conversation.title or ""):
        return cleaned_title, False

    conversation.title = cleaned_title
    await db.commit()
    await db.refresh(conversation)
    await publish_conversation_title_updated(conversation, source="generated")
    return conversation.title, True


def build_conversation_response(
    conversation: Conversation,
    db: Session,
    current_user: Optional[User] = None,
    message_count: Optional[int] = None,
    feedback_count: Optional[int] = None,
    assistant_message_count: Optional[int] = None,
    awaiting_user_input: Optional[bool] = None,
    context_usage: Optional[Dict[str, int]] = None,
    conversation_state: Optional[ConversationState] = None,
    owner_info: Optional[Tuple[Optional[str], Optional[str]]] = None,
    skip_feedback_check: bool = False,
) -> ConversationResponse:
    """Build a ConversationResponse from a Conversation model.

    Args:
        conversation: Conversation model instance
        db: Database session
        current_user: Optional user for ownership context
        message_count: Optional precomputed message count
        feedback_count: Optional precomputed feedback count for assistant messages
        assistant_message_count: Optional precomputed assistant message count
        owner_info: Optional tuple of (owner_name, owner_email) to skip User query
        skip_feedback_check: If True, skip feedback requirement check (for new branches)

    Returns:
        ConversationResponse schema instance populated with ownership metadata
    """
    if message_count is None:
        own_message_count = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation.id,
                Message.role.in_(("user", "assistant")),
            )
            .count()
        )
        message_count = _resolve_effective_message_count(conversation, own_message_count)
    else:
        message_count = _resolve_effective_message_count(conversation, int(message_count))

    resolved_state = conversation_state or getattr(conversation, "state", None)
    if awaiting_user_input is None:
        if resolved_state is None:
            resolved_state = (
                db.query(ConversationState)
                .filter(
                    ConversationState.conversation_id == conversation.id,
                )
                .first()
            )
        awaiting_user_input = bool(getattr(resolved_state, "awaiting_user_input", False)) if resolved_state is not None else False

    resolved_context_usage = context_usage
    if resolved_context_usage is None and resolved_state is not None:
        resolved_context_usage = _build_context_usage_from_state(resolved_state)

    owner_name: Optional[str] = None
    owner_email: Optional[str] = None

    if owner_info is not None:
        owner_name, owner_email = owner_info
    else:
        owner: Optional[User] = getattr(conversation, "user", None)
        if owner is None:
            owner = (
                db.query(User)
                .filter(User.id == conversation.user_id)
                .first()
            )
        if owner is not None:
            owner_email = owner.email
            owner_name = owner.name or owner.email

    is_owner = False
    if current_user is not None:
        is_owner = conversation.user_id == getattr(current_user, "id", None)

    can_edit = is_owner and not conversation.archived

    # Check if feedback is required (only for owners, non-archived conversations)
    # Admins are exempt from feedback gating
    # Skip for new branches so feedback starts from branch activity, not the parent transcript.
    requires_feedback = False
    if not skip_feedback_check:
        is_admin = (
            str(getattr(current_user, "role", "")).lower() == "admin"
            if current_user is not None
            else False
        )
        if is_owner and not conversation.archived and not is_admin:
            if assistant_message_count is not None and feedback_count is not None:
                requires_feedback = requires_feedback_from_metadata(
                    metadata=conversation.conversation_metadata,
                    feedback_count=feedback_count or 0,
                    assistant_message_count=assistant_message_count,
                )
            else:
                requires_feedback = check_requires_feedback(
                    conversation,
                    db,
                    feedback_count=feedback_count,
                    assistant_message_count=assistant_message_count,
                )

    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=format_utc_z(conversation.created_at) or "",
        updated_at=format_utc_z(conversation.updated_at) or "",
        last_message_at=(
            format_utc_z(conversation.last_message_at)
            if getattr(conversation, "last_message_at", None)
            else (format_utc_z(conversation.updated_at) or "")
        ),
        message_count=message_count,
        project_id=conversation.project_id,
        parent_conversation_id=conversation.parent_conversation_id,
        branch_from_message_id=getattr(conversation, "branch_from_message_id", None),
        archived=conversation.archived,
        archived_at=(
            format_utc_z(conversation.archived_at)
            if getattr(conversation, "archived_at", None)
            else None
        ),
        archived_by=(
            str(conversation.archived_by)
            if getattr(conversation, "archived_by", None)
            else None
        ),
        is_pinned=bool(getattr(conversation, "is_pinned", False)),
        pinned_at=format_utc_z(getattr(conversation, "pinned_at", None)),
        owner_id=conversation.user_id,
        owner_name=owner_name,
        owner_email=owner_email,
        is_owner=is_owner,
        can_edit=can_edit,
        requires_feedback=requires_feedback,
        awaiting_user_input=bool(awaiting_user_input),
        context_usage=resolved_context_usage,
    )


def archive_conversation_record(conversation: Conversation, actor_id: str) -> Optional[datetime]:
    """Mark a conversation as archived if not already archived.

    Args:
        conversation: Conversation model instance to archive
        actor_id: ID of the user performing the archive action

    Returns:
        Timestamp of archival if successful, None if already archived
    """
    if conversation.archived:
        return None

    now = datetime.now(timezone.utc)
    conversation.archived = True
    conversation.archived_at = now
    conversation.archived_by = actor_id
    return now
