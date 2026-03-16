import logging

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File as FastAPIFile
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from pathlib import Path

from ..auth.dependencies import get_current_user
from ..config.database import get_async_db, get_db
from ..database.models import User, Project, Conversation, ProjectMember, Message, File as FileModel
from ..schemas.projects_core import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectWithConversationCount,
)
from ..services.project_permissions import (
    require_project_owner,
    require_project_member,
    get_project_member,
)
from ..services.project_images import build_public_image_url
from .projects_core_collaboration import register_collaboration_routes
from .projects_core_knowledge import register_knowledge_base_routes
from ..chat.schemas import ConversationResponse
from ..chat.services.conversation_service import build_conversation_response
from ..schemas.files import (
    ProjectKnowledgeFile,
    ProjectKnowledgeUploader,
)
from ..services.files import (
    blob_storage_service,
    file_service,
    IMAGE_EXTENSIONS,
    IMAGE_MIME_TYPES,
)
from ..services.admin import analytics_event_recorder
from ..logging import log_event

router = APIRouter(prefix="/projects", tags=["projects"])
MAX_PUBLIC_IMAGE_BYTES = 2 * 1024 * 1024  # 2 MiB ceiling for browse tile images
logger = logging.getLogger(__name__)


def _serialize_project_knowledge_file(file: FileModel) -> ProjectKnowledgeFile:
    uploader = getattr(file, "user", None)
    return ProjectKnowledgeFile(
        id=file.id,
        project_id=file.project_id or "",
        filename=file.filename,
        original_filename=file.original_filename,
        file_type=file.file_type,
        file_size=file.file_size,
        created_at=file.created_at,
        updated_at=file.updated_at,
        uploaded_by=ProjectKnowledgeUploader(
            id=file.user_id,
            name=getattr(uploader, "name", None),
            email=getattr(uploader, "email", None),
        ),
        processing_status=getattr(file, "processing_status", "completed"),
        indexed_chunk_count=int(getattr(file, "indexed_chunk_count", 0) or 0),
        indexed_at=getattr(file, "indexed_at", None),
        processing_error=getattr(file, "processing_error", None),
    )


def _get_project_for_member(project_id: str, user: User, db: Session) -> Project:
    row = (
        db.query(Project, ProjectMember.role.label("member_role"))
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(
            Project.id == project_id,
            Project.archived == False,
            ProjectMember.user_id == user.id,
        )
        .first()
    )

    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    project, member_role = row
    setattr(project, "current_user_role", member_role)
    _hydrate_public_image_url(project)

    return project


def _set_current_user_role(project: Optional[Project], user_id: Optional[str], db: Session) -> None:
    if not project or not user_id:
        if project is not None:
            setattr(project, "current_user_role", None)
            _hydrate_public_image_url(project)
        return
    member = get_project_member(user_id, project.id, db)
    setattr(project, "current_user_role", getattr(member, "role", None))
    _hydrate_public_image_url(project)


def _hydrate_public_image_url(project: Optional[Project]) -> None:
    if not project:
        return
    project.public_image_url = build_public_image_url(
        project,
        expiry_minutes=1440,
        append_version=False,
    )


def _count_project_owners(project_id: str, db: Session) -> int:
    """Count project owners with FOR UPDATE lock for safe mutation.

    LAT-005: Locking all owner membership rows prevents two concurrent
    leave/demote requests from both reading owner_count=2 and both
    proceeding, which would leave the project with zero owners.
    """
    return len(
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        .with_for_update()
        .all()
    )


def _assign_new_primary_owner(project: Project, db: Session, exclude_user_id: Optional[str] = None) -> None:
    if not project:
        return
    query = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project.id, ProjectMember.role == "owner")
        .order_by(ProjectMember.joined_at.asc())
    )
    if exclude_user_id:
        query = query.filter(ProjectMember.user_id != exclude_user_id)

    replacement = query.first()
    if replacement and replacement.user_id:
        project.user_id = replacement.user_id


## display order normalization moved to services.project_ordering


def _archive_project(db: Session, project: Project, performed_by: str) -> None:
    """Archive a project and all active conversations."""
    now = datetime.now(timezone.utc)

    project.archived = True
    project.archived_at = now
    project.archived_by = performed_by

    conversations = db.query(Conversation).filter(
        Conversation.project_id == project.id,
        Conversation.archived == False,
    ).all()

    for conversation in conversations:
        conversation.archived = True
        conversation.archived_at = now
        conversation.archived_by = performed_by

    db.flush()


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new project.
    Files can be added separately via the knowledge-base upload endpoint after creation.
    """
    from ..schemas.projects_core import MAX_PROJECT_NAME_LENGTH

    try:
        # Create new project
        project = Project(
            user_id=user.id,
            name=payload.name,
            description=payload.description,
            custom_instructions=payload.custom_instructions,
            color=payload.color,
        )
        db.add(project)
        db.flush()  # Get project.id

        # Add creator as owner member
        owner_member = ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role="owner"
        )
        db.add(owner_member)

        db.commit()
        db.refresh(project)

        # Record stats for project creation
        try:
            analytics_event_recorder.record_project_created(db, user.id, project.id)
            db.commit()
        except Exception:
            pass  # Don't fail project creation if stats recording fails

        _set_current_user_role(project, user.id, db)
        return project
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to create project: {str(e)}")


@router.get("", response_model=List[ProjectWithConversationCount])
def list_projects(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all non-archived projects the user can access with conversation counts."""
    try:
        member_projects_subquery = (
            db.query(
                ProjectMember.project_id.label("project_id"),
                ProjectMember.role.label("member_role"),
            )
            .filter(ProjectMember.user_id == user.id)
            .subquery()
        )

        conversation_counts_subquery = (
            db.query(
                Conversation.project_id.label("project_id"),
                func.count(Conversation.id).label("conversation_count"),
            )
            .join(member_projects_subquery, member_projects_subquery.c.project_id == Conversation.project_id)
            .join(Project, Project.id == Conversation.project_id)
            .filter(
                Conversation.archived.is_(False),
                or_(
                    Conversation.user_id == user.id,
                    Project.is_public_candidate.is_(False),
                    Project.is_public_candidate.is_(None),
                ),
            )
            .group_by(Conversation.project_id)
            .subquery()
        )

        # Keep the row set as one project membership row and join pre-aggregated counts.
        projects = (
            db.query(
                Project,
                func.coalesce(conversation_counts_subquery.c.conversation_count, 0).label("conversation_count"),
                member_projects_subquery.c.member_role.label("member_role"),
            )
            .join(member_projects_subquery, member_projects_subquery.c.project_id == Project.id)
            .outerjoin(conversation_counts_subquery, conversation_counts_subquery.c.project_id == Project.id)
            .filter(
                Project.archived.is_(False),
            )
            .order_by(Project.created_at.asc())
            .all()
        )

        results: List[ProjectWithConversationCount] = []
        for project, count, member_role in projects:
            _hydrate_public_image_url(project)
            payload = {
                key: getattr(project, key)
                for key in (
                    "id",
                    "user_id",
                    "name",
                    "description",
                    "custom_instructions",
                    "color",
                    "category",
                    "public_image_url",
                    "public_image_updated_at",
                    "created_at",
                    "updated_at",
                )
            }
            payload["is_public"] = bool(project.is_public)
            payload["is_public_candidate"] = bool(project.is_public_candidate)
            payload["current_user_role"] = member_role
            payload["conversation_count"] = max(0, int(count or 0))
            results.append(
                ProjectWithConversationCount(**payload)
            )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch projects: {str(e)}")


@router.get("/{project_id:uuid}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a specific non-archived project by ID, including current user's role."""
    pid = str(project_id)
    return _get_project_for_member(pid, user, db)


register_knowledge_base_routes(
    router,
    get_project_for_member=_get_project_for_member,
    serialize_project_knowledge_file=_serialize_project_knowledge_file,
)


@router.put("/{project_id:uuid}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a project's metadata (name, description, custom_instructions, color, category)."""
    pid = str(project_id)
    require_project_owner(user, pid, db)

    project = (
        db.query(Project)
        .filter(
            Project.id == pid,
            Project.archived == False,
        )
        .first()
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        if payload.name is not None:
            project.name = payload.name
        if payload.description is not None:
            project.description = payload.description
        if payload.custom_instructions is not None:
            project.custom_instructions = payload.custom_instructions
        if payload.color is not None:
            project.color = payload.color
        if payload.category is not None:
            # Normalize empty string to None
            project.category = payload.category.strip() or None
        db.commit()
        db.refresh(project)
        _set_current_user_role(project, user.id, db)
        return project
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to update project: {str(e)}")


@router.post("/{project_id:uuid}/public-image", response_model=ProjectResponse)
async def upload_public_project_image(
    project_id: UUID,
    image: UploadFile = FastAPIFile(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Upload or replace the hero image used on the browse page for public projects."""
    pid = str(project_id)
    project = await db.run_sync(
        lambda sync_db: (
            require_project_owner(user, pid, sync_db),
            _get_project_for_member(pid, user, sync_db),
        )[1]
    )
    if not project.is_public_candidate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only public-intended projects can manage a public image",
        )

    contents = await image.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image file is empty",
        )
    if len(contents) > MAX_PUBLIC_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Image must be 2 MB or smaller",
        )

    content_type = (image.content_type or "").lower()
    if content_type not in IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported image type",
        )

    extension = Path(image.filename or "").suffix.lower().lstrip(".")
    if not extension or extension not in IMAGE_EXTENSIONS:
        if content_type == "image/png":
            extension = "png"
        elif content_type in {"image/jpeg", "image/jpg"}:
            extension = "jpg"
        elif content_type == "image/gif":
            extension = "gif"
        elif content_type == "image/webp":
            extension = "webp"
        else:
            extension = "png"

    blob_name = f"public-projects/{pid}/{uuid4().hex}.{extension}"

    try:
        blob_url = await blob_storage_service.upload(blob_name, contents)
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "projects.public_image.upload_failed",
            "error",
            user_id=str(user.id),
            project_id=pid,
            content_type=content_type,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload image",
        )

    old_blob = project.public_image_blob
    project.public_image_blob = blob_name
    project.public_image_url = blob_url
    project.public_image_updated_at = datetime.now(timezone.utc)

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        try:
            blob_storage_service.delete(blob_name)
        except Exception as cleanup_exc:
            log_event(
                logger,
                "ERROR",
                "projects.public_image.cleanup_failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                blob_name=blob_name,
                error_type=type(cleanup_exc).__name__,
                exc_info=cleanup_exc,
            )
        log_event(
            logger,
            "ERROR",
            "projects.public_image.persist_failed",
            "error",
            user_id=str(user.id),
            project_id=pid,
            blob_name=blob_name,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist image metadata",
        )

    await db.refresh(project)
    await db.run_sync(lambda sync_db: _set_current_user_role(project, user.id, sync_db))

    if old_blob and old_blob != blob_name:
        try:
            blob_storage_service.delete(old_blob)
        except Exception as exc:
            log_event(
                logger,
                "ERROR",
                "projects.public_image.previous_blob_cleanup_failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                blob_name=old_blob,
                error_type=type(exc).__name__,
                exc_info=exc,
            )

    return project


@router.delete("/{project_id:uuid}/public-image", response_model=ProjectResponse)
def delete_public_project_image(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove the hero image for a public project."""
    pid = str(project_id)
    require_project_owner(user, pid, db)

    project = _get_project_for_member(pid, user, db)
    if not project.is_public_candidate:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only public-intended projects can manage a public image",
        )

    old_blob = project.public_image_blob
    project.public_image_blob = None
    project.public_image_url = None
    project.public_image_updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(project)
    _set_current_user_role(project, user.id, db)

    if old_blob:
        try:
            blob_storage_service.delete(old_blob)
        except Exception as exc:
            log_event(
                logger,
                "ERROR",
                "projects.public_image.delete_cleanup_failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                blob_name=old_blob,
                error_type=type(exc).__name__,
                exc_info=exc,
            )

    return project


@router.delete("/{project_id:uuid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Archive a project and all its conversations. Only owner can delete."""
    # Check owner permission
    pid = str(project_id)
    require_project_owner(user, pid, db)

    project = db.query(Project).filter(
        Project.id == pid,
        Project.archived == False
    ).first()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        _archive_project(db, project, user.id)
        db.commit()
        file_service.purge_archived_project_blob_content_best_effort(
            db=db,
            project_ids=[pid],
            user_id=str(user.id),
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to delete project: {str(e)}")


# Reorder endpoint removed (feature deprecated)


register_collaboration_routes(
    router,
    count_project_owners=_count_project_owners,
    assign_new_primary_owner=_assign_new_primary_owner,
    archive_project=_archive_project,
)


@router.get("/{project_id:uuid}/conversations", response_model=List[ConversationResponse])
def get_project_conversations(
    project_id: UUID,
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all conversations in a project. Requires project membership."""
    # Check if user is a project member
    pid = str(project_id)
    require_project_member(user, pid, db)

    project = db.query(Project).filter(
        Project.id == pid,
        Project.archived == False,
    )
    project_obj = project.first()
    if not project_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Build query
    query = db.query(Conversation).filter(Conversation.project_id == pid)

    if not include_archived:
        query = query.filter(Conversation.archived == False)

    if bool(project_obj.is_public_candidate):
        query = query.filter(Conversation.user_id == user.id)

    conversations = (
        query.options(joinedload(Conversation.user))
        .options(joinedload(Conversation.state))
        .order_by(Conversation.last_message_at.desc())
        .all()
    )

    conv_ids = [c.id for c in conversations]
    counts_map = {}
    if conv_ids:
        rows = (
            db.query(Message.conversation_id, func.count(Message.id))
            .filter(
                Message.conversation_id.in_(conv_ids),
                Message.role.in_(("user", "assistant")),
            )
            .group_by(Message.conversation_id)
            .all()
        )
        counts_map = {cid: int(count) for cid, count in rows}

    return [
        build_conversation_response(
            conv,
            db,
            current_user=user,
            message_count=counts_map.get(conv.id, 0),
        )
        for conv in conversations
    ]
