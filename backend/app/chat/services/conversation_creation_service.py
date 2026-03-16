"""Service for conversation creation logic."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ...database.models import Conversation, File, Project, User
from ...logging import log_event
from ...services.admin import analytics_event_recorder
from ...services.project_permissions import require_project_member

logger = logging.getLogger(__name__)


def check_conversation_idempotency(
    request_id: str,
    user_id: str,
    db: Session,
) -> Optional[Conversation]:
    """Check if a conversation already exists with the given request_id.

    Args:
        request_id: The idempotency key to search for
        user_id: The ID of the user who owns the messages
        db: Database session

    Returns:
        Existing conversation if found, None otherwise
    """
    request_id = (request_id or "").strip()
    if not request_id:
        return None

    return (
        db.query(Conversation)
        .filter(
            Conversation.user_id == user_id,
            Conversation.creation_request_id == request_id,
        )
        .first()
    )


def normalize_creation_request_id(request_id: Optional[str]) -> Optional[str]:
    if not isinstance(request_id, str):
        return None
    cleaned = request_id.strip()
    return cleaned or None


def normalize_conversation_project_id(project_id: Optional[str]) -> Optional[str]:
    if not isinstance(project_id, str):
        return None
    cleaned = project_id.strip()
    return cleaned or None


def normalize_conversation_title(title: Optional[str]) -> str:
    raw_title = title if isinstance(title, str) else ""
    normalized = raw_title.strip()[:255]
    return normalized or "New Chat"


def normalize_conversation_id(conversation_id: Optional[str]) -> Optional[str]:
    if not isinstance(conversation_id, str):
        return None
    cleaned = conversation_id.strip()
    if not cleaned:
        return None
    try:
        UUID(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="conversation_id must be a valid UUID") from exc
    return cleaned


def find_conversation_for_owner_by_id(
    *,
    db: Session,
    current_user: User,
    conversation_id: Optional[str],
) -> Optional[Conversation]:
    normalized_conversation_id = normalize_conversation_id(conversation_id)
    if normalized_conversation_id is None:
        return None
    return (
        db.query(Conversation)
        .filter(
            Conversation.id == normalized_conversation_id,
            Conversation.user_id == current_user.id,
        )
        .first()
    )


def validate_conversation_project_access(
    *,
    db: Session,
    current_user: User,
    project_id: Optional[str],
) -> Optional[str]:
    normalized_project_id = normalize_conversation_project_id(project_id)
    if normalized_project_id is None:
        return None

    project = (
        db.query(Project)
        .filter(
            Project.id == normalized_project_id,
            Project.archived == False,  # noqa: E712
        )
        .first()
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    require_project_member(current_user, normalized_project_id, db)
    return normalized_project_id


def create_conversation_record(
    *,
    db: Session,
    current_user: User,
    request_id: Optional[str],
    project_id: Optional[str],
    title: Optional[str],
    conversation_id: Optional[str] = None,
) -> Conversation:
    conversation_kwargs: Dict[str, Any] = {
        "user_id": current_user.id,
        "project_id": validate_conversation_project_access(
            db=db,
            current_user=current_user,
            project_id=project_id,
        ),
        "title": normalize_conversation_title(title),
        "creation_request_id": normalize_creation_request_id(request_id),
    }
    normalized_conversation_id = normalize_conversation_id(conversation_id)
    if normalized_conversation_id is not None:
        conversation_kwargs["id"] = normalized_conversation_id

    conversation = Conversation(**conversation_kwargs)
    conversation.last_message_at = datetime.now(timezone.utc)
    db.add(conversation)

    try:
        analytics_event_recorder.record_new_conversation(db, user_id=str(current_user.id))
    except Exception as exc:
        log_event(
            logger,
            "WARNING",
            "admin.stats.conversation_record_failed",
            "retry",
            user_id=str(current_user.id),
            conversation_id=str(getattr(conversation, "id", "")),
            exc_info=exc,
        )

    return conversation


def build_attachment_metadata_list(files: List[File]) -> List[Dict[str, Any]]:
    """Build attachment metadata list from promoted files.

    Args:
        files: List of File records

    Returns:
        List of attachment metadata dictionaries
    """
    attachments_meta: List[Dict[str, Any]] = []

    for f in files:
        attachments_meta.append(
            {
                "id": f.id,
                "filename": f.filename,
                "original_filename": f.original_filename,
                "file_type": f.file_type,
                "file_size": int(f.file_size or 0),
                "uploaded_at": f.created_at.isoformat() + 'Z' if f.created_at else None,
                "checksum": f.content_hash,
            }
        )

    return attachments_meta
