from copy import deepcopy
from datetime import datetime, timedelta, timezone
import logging
import secrets
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..chat.services.conversation_service import (
    FEEDBACK_MESSAGES_INTERVAL,
    FEEDBACK_METADATA_VERSION,
)
from ..chat.services.event_store_service import append_event_sync
from ..config.database import get_db
from ..config.settings import settings
from ..database.models import (
    Conversation,
    ConversationShare,
    Message,
    Project,
    ProjectMember,
    ProjectShare,
    User,
)
from ..schemas.projects_core import ProjectJoinResponse
from ..schemas.share import ShareImportResponse, ShareResponse
from ..services.admin import analytics_event_recorder
from ..logging import log_event

router = APIRouter()
logger = logging.getLogger(__name__)

_VISIBLE_SHARE_ROLES = ("user", "assistant")


@router.post("/conversations/{conversation_id}/share", response_model=ShareResponse)
def create_share_link(
    conversation_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a shareable link for a conversation snapshot (7-day expiry)."""
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
    ).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    now = datetime.now(timezone.utc)
    share_token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=7)

    snapshot_messages = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.role.in_(_VISIBLE_SHARE_ROLES),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )

    message_ids = [message.id for message in snapshot_messages]

    new_share = ConversationShare(
        id=str(uuid.uuid4()),
        conversation_id=conversation_id,
        share_token=share_token,
        created_by=current_user.id,
        expires_at=expires_at,
        event_snapshot={"message_ids": message_ids},
    )

    db.add(new_share)
    analytics_event_recorder.record_share_created(db, current_user.id, new_share.id)
    db.commit()
    db.refresh(new_share)

    frontend_url = settings.resolve_frontend_url(request.headers.get("origin"))
    share_url = f"{frontend_url}/share/{share_token}"
    return ShareResponse(
        share_token=share_token,
        share_url=share_url,
        expires_at=expires_at,
    )


@router.post("/share/{share_token}/import", response_model=ShareImportResponse)
def import_shared_conversation(
    share_token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import a shared conversation into the current user's account."""
    share = db.query(ConversationShare).filter(
        ConversationShare.share_token == share_token,
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found")

    if share.expires_at:
        expires_at = share.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at = expires_at.astimezone(timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Share link has expired")

    original_conversation = db.query(Conversation).filter(
        Conversation.id == share.conversation_id,
    ).first()
    if not original_conversation:
        raise HTTPException(status_code=404, detail="Original conversation not found")

    existing_import = (
        db.query(Conversation)
        .filter(
            Conversation.user_id == current_user.id,
            Conversation.import_source_token == share_token,
            Conversation.archived == False,
        )
        .first()
    )
    if existing_import:
        return ShareImportResponse(
            conversation_id=existing_import.id,
            title=existing_import.title,
            message="You have already imported this share link",
        )

    original_title = original_conversation.title or "New Chat"
    new_title = f"Shared - {original_title}"

    now = datetime.now(timezone.utc)
    metadata: Dict[str, Any] = {
        "shared_from": share.conversation_id,
        "shared_from_token": share_token,
        "shared_at": now.isoformat(),
        "original_owner_id": original_conversation.user_id,
    }
    if isinstance(original_conversation.conversation_metadata, dict):
        usage_snapshot = original_conversation.conversation_metadata.get("usage")
        if isinstance(usage_snapshot, dict) and usage_snapshot:
            metadata["usage"] = deepcopy(usage_snapshot)

    try:
        feedback_meta = {
            "version": int(FEEDBACK_METADATA_VERSION),
            "messages_per_cycle": int(FEEDBACK_MESSAGES_INTERVAL),
        }
        metadata_feedback = dict(metadata.get("feedback") or {})
        metadata_feedback.update(feedback_meta)
        metadata["feedback"] = metadata_feedback
    except Exception:
        pass

    new_conversation = Conversation(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        title=new_title,
        import_source_token=share_token,
        conversation_metadata=metadata,
        last_message_at=now,
    )
    db.add(new_conversation)
    db.flush()

    snapshot_message_ids: List[str] = []
    if share.event_snapshot and isinstance(share.event_snapshot, dict):
        raw_ids = share.event_snapshot.get("message_ids", [])
        if isinstance(raw_ids, list):
            snapshot_message_ids = [eid for eid in raw_ids if isinstance(eid, str) and eid]

    messages_to_clone: List[Message] = []
    if snapshot_message_ids:
        rows = (
            db.query(Message)
            .filter(Message.id.in_(set(snapshot_message_ids)))
            .all()
        )
        rows_by_id = {row.id: row for row in rows}
        messages_to_clone = [rows_by_id[eid] for eid in snapshot_message_ids if eid in rows_by_id]
    else:
        messages_to_clone = (
            db.query(Message)
            .filter(
                Message.conversation_id == original_conversation.id,
                Message.role.in_(_VISIBLE_SHARE_ROLES),
            )
            .order_by(Message.created_at.asc(), Message.id.asc())
            .all()
        )

    for original_message in messages_to_clone:
        payload: Dict[str, Any] = {
            "text": original_message.text or "",
            "status": original_message.status,
            "model_provider": original_message.model_provider,
            "model_name": original_message.model_name,
            "finish_reason": original_message.finish_reason,
            "response_latency_ms": original_message.response_latency_ms,
            "cost_usd": float(original_message.cost_usd) if original_message.cost_usd is not None else None,
            "source_message_id": original_message.id,
        }
        event_type = "user_message" if original_message.role == "user" else (
            "assistant_message_partial"
            if str(original_message.status or "").strip().lower() in {"streaming", "awaiting_input", "paused"}
            else "assistant_message_final"
        )
        append_event_sync(
            db,
            conversation_id=new_conversation.id,
            event_type=event_type,
            actor=original_message.role,
            phase="worklog" if event_type == "assistant_message_partial" else "final",
            payload=payload,
            created_at=original_message.created_at,
        )

    analytics_event_recorder.record_share_imported(db, current_user.id, share.id)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing_import = (
            db.query(Conversation)
            .filter(
                Conversation.user_id == current_user.id,
                Conversation.import_source_token == share_token,
                Conversation.archived == False,
            )
            .first()
        )
        if existing_import:
            return ShareImportResponse(
                conversation_id=existing_import.id,
                title=existing_import.title,
                message="You have already imported this share link",
            )
        raise
    db.refresh(new_conversation)

    return ShareImportResponse(
        conversation_id=new_conversation.id,
        title=new_conversation.title,
        message="Conversation imported successfully",
    )


@router.post("/share/projects/{share_token}/join", response_model=ProjectJoinResponse)
def join_project_via_share_link(
    share_token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Join a project using a valid project share link."""
    share = db.query(ProjectShare).filter(
        ProjectShare.share_token == share_token,
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share link not found")

    if share.expires_at:
        expires_at = share.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        else:
            expires_at = expires_at.astimezone(timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Share link has expired")

    project = db.query(Project).filter(
        Project.id == share.project_id,
        Project.archived == False,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or archived")

    new_member = ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        role="member",
    )

    try:
        db.add(new_member)
        db.commit()

        try:
            analytics_event_recorder.record_member_joined(db, current_user.id, project.id)
            db.commit()
        except Exception:
            pass

        return ProjectJoinResponse(
            project_id=project.id,
            project_name=project.name,
            message="Successfully joined project",
        )
    except IntegrityError as exc:
        db.rollback()
        try:
            existing_member = (
                db.query(ProjectMember)
                .filter(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == current_user.id,
                )
                .first()
            )
        except Exception as lookup_exc:
            existing_member = None
            log_event(
                logger,
                "ERROR",
                "share.project_join.integrity_recheck.failed",
                "error",
                user_id=str(current_user.id),
                project_id=str(project.id),
                share_id=str(getattr(share, "id", "")) or None,
                error_type=type(lookup_exc).__name__,
                exc_info=lookup_exc,
            )
        if existing_member:
            return ProjectJoinResponse(
                project_id=project.id,
                project_name=project.name,
                message="You are already a member of this project",
            )
        log_event(
            logger,
            "ERROR",
            "share.project_join.failed",
            "error",
            user_id=str(current_user.id),
            project_id=str(project.id),
            share_id=str(getattr(share, "id", "")) or None,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to join project",
        ) from exc
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "ERROR",
            "share.project_join.failed",
            "error",
            user_id=str(current_user.id),
            project_id=str(project.id),
            share_id=str(getattr(share, "id", "")) or None,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to join project",
        )
