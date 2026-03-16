"""Conversation CRUD, branching, archiving, and project assignment routes."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import Integer, and_, or_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Dict
from datetime import datetime, timezone
import logging

from ...database import get_db, get_async_db
from ...database.models import (
    CONSTRAINT_CONVERSATIONS_USER_CREATION_REQUEST,
    User,
    Conversation,
    Message,
    MessageFeedback,
    ConversationState,
    Project,
    ProjectMember,
)
from ...auth.dependencies import get_current_user
from ...services.project_permissions import (
    require_conversation_owner,
    can_access_conversation,
    require_project_member,
)
from ...services.admin import analytics_event_recorder
from ...logging import log_event
from ...services.chat_streams import get_local_stream, request_cancel
from ...services.files import file_service
from ...utils.datetime_helpers import format_utc_z
from ...utils.integrity import is_constraint_violation
from ...utils.coerce import normalize_uuid_string

from ..schemas import (
    CreateConversationRequest,
    ConversationResponse,
    BranchConversationRequest,
    ProjectAssignmentRequest,
    BulkArchiveRequest,
    BulkArchiveResponse,
)
from ..services.conversation_service import (
    build_conversation_response,
    archive_conversation_record,
    FEEDBACK_MESSAGES_INTERVAL,
    FEEDBACK_METADATA_VERSION,
)
from ..services.conversation_creation_service import (
    check_conversation_idempotency,
    create_conversation_record,
    find_conversation_for_owner_by_id,
    normalize_creation_request_id,
)
from ..services.conversation_branching_service import (
    clone_files_with_mapping,
    clone_messages_for_branch,
    collect_file_ids_from_messages,
)
logger = logging.getLogger(__name__)
router = APIRouter()

_CONVERSATION_CREATE_IDEMPOTENCY_CONSTRAINTS = {
    CONSTRAINT_CONVERSATIONS_USER_CREATION_REQUEST,
}


def _normalize_conversation_id_or_404(conversation_id: str) -> str:
    normalized_conversation_id = normalize_uuid_string(conversation_id)
    if normalized_conversation_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return normalized_conversation_id


async def _stop_archived_stream(conversation_id: str) -> None:
    """Best-effort immediate stop for archived conversations."""
    try:
        await request_cancel(conversation_id)
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.archive.cancel_flag_set_failed",
            "retry",
            conversation_id=conversation_id,
            exc_info=True,
        )

    try:
        local_stream = get_local_stream(conversation_id)
        if local_stream and not local_stream.task.done():
            local_stream.task.cancel()
    except Exception:
        log_event(
            logger,
            "WARNING",
            "chat.archive.local_task_cancel_failed",
            "retry",
            conversation_id=conversation_id,
            exc_info=True,
        )


def _build_created_conversation_response(
    *,
    conversation: Conversation,
    db: Session,
    current_user: User,
) -> ConversationResponse:
    return build_conversation_response(
        conversation,
        db,
        current_user=current_user,
        message_count=0,
        assistant_message_count=0,
        awaiting_user_input=False,
        owner_info=(current_user.name, current_user.email),
        skip_feedback_check=True,
    )


@router.post("/", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    request_id = normalize_creation_request_id(payload.request_id)
    existing_by_id = find_conversation_for_owner_by_id(
        db=db,
        current_user=current_user,
        conversation_id=payload.conversation_id,
    )
    if existing_by_id is not None and not bool(getattr(existing_by_id, "archived", False)):
        return _build_created_conversation_response(
            conversation=existing_by_id,
            db=db,
            current_user=current_user,
        )

    if request_id:
        existing = check_conversation_idempotency(request_id, str(current_user.id), db)
        if existing is not None and not bool(getattr(existing, "archived", False)):
            return _build_created_conversation_response(
                conversation=existing,
                db=db,
                current_user=current_user,
            )

    conversation = create_conversation_record(
        db=db,
        current_user=current_user,
        request_id=request_id,
        project_id=payload.project_id,
        title=payload.title,
        conversation_id=payload.conversation_id,
    )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing_by_id = find_conversation_for_owner_by_id(
            db=db,
            current_user=current_user,
            conversation_id=payload.conversation_id,
        )
        if existing_by_id is not None and not bool(getattr(existing_by_id, "archived", False)):
            log_event(
                logger,
                "INFO",
                "chat.conversation.create.client_id_reused",
                "timing",
                user_id=str(current_user.id),
                conversation_id=str(existing_by_id.id),
            )
            return _build_created_conversation_response(
                conversation=existing_by_id,
                db=db,
                current_user=current_user,
            )
        if request_id and is_constraint_violation(exc, _CONVERSATION_CREATE_IDEMPOTENCY_CONSTRAINTS):
            existing = check_conversation_idempotency(request_id, str(current_user.id), db)
            if existing is not None and not bool(getattr(existing, "archived", False)):
                log_event(
                    logger,
                    "INFO",
                    "chat.conversation.create.idempotent_reused",
                    "timing",
                    user_id=str(current_user.id),
                    conversation_id=str(existing.id),
                )
                return _build_created_conversation_response(
                    conversation=existing,
                    db=db,
                    current_user=current_user,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Duplicate conversation request for this user",
            ) from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(conversation)

    return build_conversation_response(
        conversation,
        db,
        current_user=current_user,
        message_count=0,
        assistant_message_count=0,
        feedback_count=0,
        awaiting_user_input=False,
        skip_feedback_check=True,
    )


@router.post("/{conversation_id}/branch", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
def branch_conversation(
    conversation_id: str,
    branch_request: BranchConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized_conversation_id = _normalize_conversation_id_or_404(conversation_id)
    conversation: Optional[Conversation] = (
        db.query(Conversation)
        .filter(Conversation.id == normalized_conversation_id)
        .first()
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if bool(getattr(conversation, "archived", False)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if not can_access_conversation(current_user, conversation, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this conversation",
        )

    message_id = (branch_request.message_id or "").strip()
    if not message_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="message_id is required")

    anchor_message: Optional[Message] = (
        db.query(Message)
        .filter(
            Message.conversation_id == normalized_conversation_id,
            Message.id == message_id,
        )
        .first()
    )
    if anchor_message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found in conversation",
        )

    source_messages: List[Message] = (
        db.query(Message)
        .filter(
            Message.conversation_id == normalized_conversation_id,
            or_(
                Message.created_at < anchor_message.created_at,
                and_(
                    Message.created_at == anchor_message.created_at,
                    Message.id <= anchor_message.id,
                ),
            ),
        )
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    if not source_messages:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No messages available to branch from")

    inherited_message_count = sum(
        1
        for message in source_messages
        if message.role in {"user", "assistant"}
    )
    assistant_msg_count = sum(
        1
        for message in source_messages
        if message.role == "assistant" and str(message.status or "").strip().lower() in {"completed", "failed", "cancelled"}
    )

    branch_title = (conversation.title or "").strip() or "New Chat"

    branch_metadata: Dict[str, object] = {}
    if isinstance(conversation.conversation_metadata, dict):
        branch_metadata = dict(conversation.conversation_metadata)
    # Clean up any stale metadata keys from prior architectures.
    for key in ("openai_previous_response_id", "openai_previous_response_updated_at"):
        branch_metadata.pop(key, None)

    try:
        feedback_meta = dict((branch_metadata.get('feedback') or {}))
        feedback_meta.update({
            'version': int(FEEDBACK_METADATA_VERSION),
            'messages_per_cycle': int(FEEDBACK_MESSAGES_INTERVAL),
        })
        branch_metadata['feedback'] = feedback_meta
    except Exception:
        pass

    new_branch_conversation = Conversation(
        user_id=current_user.id,
        title=branch_title,
        parent_conversation_id=normalized_conversation_id,
        branch_from_message_id=anchor_message.id,
        conversation_metadata=branch_metadata,
        project_id=conversation.project_id,
    )
    new_branch_conversation.last_message_at = datetime.now(timezone.utc)
    db.add(new_branch_conversation)
    db.flush()

    source_file_ids = collect_file_ids_from_messages(source_messages)
    file_id_map = clone_files_with_mapping(
        file_ids=source_file_ids,
        source_conversation_id=normalized_conversation_id,
        target_conversation_id=new_branch_conversation.id,
        db=db,
    )
    clone_messages_for_branch(
        messages=source_messages,
        target_conversation_id=new_branch_conversation.id,
        file_id_map=file_id_map,
        db=db,
    )

    try:
        analytics_event_recorder.record_new_conversation(db, user_id=str(current_user.id))
        analytics_event_recorder.record_branch_created(db, user_id=str(current_user.id), conversation_id=str(new_branch_conversation.id))
    except Exception as exc:
        log_event(
            logger,
            "WARNING",
            "admin.stats.branch_record_failed",
            "retry",
            user_id=str(current_user.id),
            conversation_id=str(new_branch_conversation.id),
            exc_info=exc,
        )

    if conversation.project_id:
        project = (
            db.query(Project)
            .filter(
                Project.id == conversation.project_id,
                Project.archived == False,
            )
            .first()
        )
        if project:
            project.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(new_branch_conversation)

    owner_name = current_user.name or current_user.email
    owner_email = current_user.email

    return build_conversation_response(
        new_branch_conversation,
        db,
        current_user=current_user,
        message_count=inherited_message_count,
        assistant_message_count=assistant_msg_count,
        owner_info=(owner_name, owner_email),
        skip_feedback_check=True,  # New branches never require feedback immediately
    )


@router.get("/", response_model=List[ConversationResponse])
async def get_conversations(
    include_archived: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Get all conversations for the current user"""
    def _db_work(sync_db: Session) -> List[ConversationResponse]:
        # Conversations the user can access: their own, plus chats inside projects they belong to.
        member_project_ids_subq = (
            sync_db.query(ProjectMember.project_id)
            .filter(ProjectMember.user_id == current_user.id)
            .subquery()
        )

        # Order by last conversational activity, not by arbitrary updates (e.g., title changes)
        query = (
            sync_db.query(Conversation)
            .filter(
                or_(
                    Conversation.user_id == current_user.id,
                    Conversation.project_id.in_(select(member_project_ids_subq.c.project_id)),
                )
            )
        )

        if not include_archived:
            query = query.filter(Conversation.archived == False)  # noqa: E712

        accessible_conversation_ids_subq = query.with_entities(Conversation.id).subquery()

        event_counts_subq = (
            sync_db.query(
                Message.conversation_id.label("conversation_id"),
                func.coalesce(
                    func.sum(
                        func.cast(
                            Message.role.in_(("user", "assistant")),
                            Integer,
                        )
                    ),
                    0,
                ).label("message_count"),
                func.coalesce(
                    func.sum(
                        func.cast(
                            and_(
                                Message.role == "assistant",
                                Message.status.in_(("completed", "failed", "cancelled")),
                            ),
                            Integer,
                        )
                    ),
                    0,
                ).label("assistant_message_count"),
            )
            .filter(
                Message.conversation_id.in_(
                    select(accessible_conversation_ids_subq.c.id)
                )
            )
            .group_by(Message.conversation_id)
            .subquery()
        )

        feedback_counts_subq = (
            sync_db.query(
                Message.conversation_id.label("conversation_id"),
                func.count(MessageFeedback.id).label("feedback_count"),
            )
            .join(MessageFeedback, MessageFeedback.message_id == Message.id)
            .filter(
                Message.conversation_id.in_(
                    select(accessible_conversation_ids_subq.c.id)
                ),
                Message.role == "assistant",
                Message.status.in_(("completed", "failed", "cancelled")),
            )
            .group_by(Message.conversation_id)
            .subquery()
        )

        conversations_with_counts = (
            sync_db.query(Conversation)
            .options(joinedload(Conversation.user))
            .filter(
                Conversation.id.in_(
                    select(accessible_conversation_ids_subq.c.id)
                )
            )
            .outerjoin(
                event_counts_subq,
                event_counts_subq.c.conversation_id == Conversation.id,
            )
            .outerjoin(
                feedback_counts_subq,
                feedback_counts_subq.c.conversation_id == Conversation.id,
            )
            .outerjoin(ConversationState, ConversationState.conversation_id == Conversation.id)
            .add_columns(
                event_counts_subq.c.message_count,
                event_counts_subq.c.assistant_message_count,
                feedback_counts_subq.c.feedback_count,
                ConversationState,
            )
            .order_by(
                Conversation.is_pinned.desc(),
                Conversation.pinned_at.desc(),
                Conversation.last_message_at.desc(),
            )
            .all()
        )

        result: List[ConversationResponse] = []
        for conv, message_count, assistant_count, feedback_count, state_row in conversations_with_counts:
            result.append(
                build_conversation_response(
                    conv,
                    sync_db,
                    current_user=current_user,
                    message_count=int(message_count) if message_count is not None else 0,
                    assistant_message_count=int(assistant_count) if assistant_count is not None else 0,
                    feedback_count=int(feedback_count) if feedback_count is not None else 0,
                    awaiting_user_input=bool(getattr(state_row, "awaiting_user_input", False)) if state_row is not None else False,
                    conversation_state=state_row,
                    owner_info=(
                        getattr(getattr(conv, "user", None), "name", None),
                        getattr(getattr(conv, "user", None), "email", None),
                    ),
                )
            )

        return result

    return await db.run_sync(_db_work)


@router.post("/bulk-archive", response_model=BulkArchiveResponse)
async def bulk_archive_conversations(
    request: BulkArchiveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db)
):
    """Archive multiple conversations belonging to the current user."""
    conversation_ids = request.conversation_ids
    actor_id = str(current_user.id)

    def _archive_conversations(sync_db: Session) -> tuple[Dict[str, Conversation], List[str], List[str], Dict[str, str]]:
        conversations = (
            sync_db.query(Conversation)
            .filter(
                Conversation.user_id == current_user.id,
                Conversation.id.in_(conversation_ids)
            )
            .all()
        )

        found_map: Dict[str, Conversation] = {conv.id: conv for conv in conversations}
        archived_ids: List[str] = []
        already_archived_ids: List[str] = []
        archived_timestamps: Dict[str, str] = {}

        for conv in conversations:
            archived_at = archive_conversation_record(conv, actor_id)
            if archived_at is None:
                already_archived_ids.append(conv.id)
                continue
            archived_ids.append(conv.id)
            archived_timestamps[conv.id] = format_utc_z(archived_at) or ""

        return found_map, archived_ids, already_archived_ids, archived_timestamps

    found_map, archived_ids, already_archived_ids, archived_timestamps = await db.run_sync(_archive_conversations)

    if archived_ids:
        await db.commit()
        await db.run_sync(
            lambda sync_db: file_service.purge_archived_conversation_blob_content_best_effort(
                db=sync_db,
                conversation_ids=archived_ids,
                user_id=actor_id,
            )
        )
        await asyncio.gather(
            *(_stop_archived_stream(conversation_id) for conversation_id in archived_ids),
            return_exceptions=True,
        )
    else:
        await db.rollback()

    not_found_ids = [cid for cid in conversation_ids if cid not in found_map]

    return BulkArchiveResponse(
        archived_ids=archived_ids,
        already_archived_ids=already_archived_ids,
        not_found_ids=not_found_ids,
        archived_timestamps=archived_timestamps,
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Fetch a single conversation with ownership metadata."""
    normalized_conversation_id = _normalize_conversation_id_or_404(conversation_id)

    def _db_work(sync_db: Session) -> ConversationResponse:
        conversation = (
            sync_db.query(Conversation)
            .options(joinedload(Conversation.user), joinedload(Conversation.state))
            .filter(Conversation.id == normalized_conversation_id)
            .first()
        )

        if not conversation or getattr(conversation, "archived", False):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        if not can_access_conversation(current_user, conversation, sync_db):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this conversation",
            )

        message_count = (
            sync_db.query(Message.id)
            .filter(
                Message.conversation_id == conversation.id,
                Message.role.in_(("user", "assistant")),
            )
            .count()
        )
        assistant_message_count = (
            sync_db.query(Message.id)
            .filter(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
                Message.status.in_(("completed", "failed", "cancelled")),
            )
            .count()
        )
        feedback_count = (
            sync_db.query(MessageFeedback.id)
            .join(Message, MessageFeedback.message_id == Message.id)
            .filter(
                Message.conversation_id == conversation.id,
                Message.role == "assistant",
                Message.status.in_(("completed", "failed", "cancelled")),
            )
            .count()
        )
        state_row = getattr(conversation, "state", None)

        return build_conversation_response(
            conversation,
            sync_db,
            current_user=current_user,
            message_count=message_count,
            feedback_count=feedback_count,
            assistant_message_count=assistant_message_count,
            awaiting_user_input=bool(getattr(state_row, "awaiting_user_input", False)) if state_row is not None else False,
            conversation_state=state_row,
            owner_info=(
                getattr(getattr(conversation, "user", None), "name", None),
                getattr(getattr(conversation, "user", None), "email", None),
            ),
        )

    return await db.run_sync(_db_work)


@router.patch("/{conversation_id}/pin", response_model=ConversationResponse)
def toggle_pin_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = require_conversation_owner(current_user, conversation_id, db)
    if bool(getattr(conversation, "archived", False)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    now = datetime.now(timezone.utc)
    conversation.is_pinned = not bool(conversation.is_pinned)
    conversation.pinned_at = now if conversation.is_pinned else None
    conversation.updated_at = now
    db.commit()
    db.refresh(conversation)

    message_count = (
        db.query(Message.id)
        .filter(
            Message.conversation_id == conversation.id,
            Message.role.in_(("user", "assistant")),
        )
        .count()
    )

    return build_conversation_response(
        conversation,
        db,
        current_user=current_user,
        message_count=message_count,
        owner_info=(current_user.name, current_user.email),
    )


@router.put("/{conversation_id}/project", response_model=ConversationResponse)
def update_conversation_project(
    conversation_id: str,
    assignment: ProjectAssignmentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign or unassign a conversation to a project."""
    # Check ownership permission
    conversation = require_conversation_owner(current_user, conversation_id, db)

    if getattr(conversation, "archived", False):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    target_project_id: Optional[str] = assignment.project_id
    if target_project_id == conversation.project_id:
        return build_conversation_response(
            conversation,
            db,
            current_user=current_user,
        )

    new_project: Optional[Project] = None
    if target_project_id is not None:
        new_project = (
            db.query(Project)
            .filter(
                Project.id == target_project_id,
                Project.archived == False,
            )
            .first()
        )
        if not new_project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Project not found",
            )

        # Ensure the user can access the destination project
        require_project_member(current_user, new_project.id, db)

    previous_project_id = conversation.project_id

    conversation.project_id = new_project.id if new_project else None
    conversation.updated_at = datetime.now(timezone.utc)

    if new_project:
        new_project.updated_at = datetime.now(timezone.utc)

    if previous_project_id and previous_project_id != conversation.project_id:
        previous_project = (
            db.query(Project)
            .filter(
                Project.id == previous_project_id,
                Project.archived == False,
            )
            .first()
        )
        if previous_project:
            previous_project.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(conversation)

    return build_conversation_response(
        conversation,
        db,
        current_user=current_user,
    )
