import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone

from ..auth.dependencies import get_current_user
from ..config.database import get_db
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
from .projects_core_collaboration import register_collaboration_routes
from .projects_core_knowledge import register_knowledge_base_routes
from ..chat.schemas import ConversationResponse
from ..chat.services.conversation_service import build_conversation_response
from ..schemas.files import (
    ProjectKnowledgeFile,
    ProjectKnowledgeUploader,
)
from ..services.files import file_service
from ..services.admin import analytics_event_recorder

router = APIRouter(prefix="/projects", tags=["projects"])
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

    return project


def _set_current_user_role(project: Optional[Project], user_id: Optional[str], db: Session) -> None:
    if not project or not user_id:
        if project is not None:
            setattr(project, "current_user_role", None)
        return
    member = get_project_member(user_id, project.id, db)
    setattr(project, "current_user_role", getattr(member, "role", None))


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
            .filter(
                Conversation.archived.is_(False),
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
            payload = {
                key: getattr(project, key)
                for key in (
                    "id",
                    "user_id",
                    "name",
                    "description",
                    "custom_instructions",
                    "color",
                    "created_at",
                    "updated_at",
                )
            }
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
    """Update a project's metadata."""
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
        db.commit()
        db.refresh(project)
        _set_current_user_role(project, user.id, db)
        return project
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Failed to update project: {str(e)}")


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
