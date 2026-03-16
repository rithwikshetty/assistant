import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, func
from typing import List, Optional
from uuid import UUID

from ..auth.dependencies import get_current_user
from ..config.database import get_db
from ..database.models import User, Project, ProjectMember, Conversation
from ..schemas.projects import (
    BrowseProjectsResponse,
    BrowseProjectItem,
    BrowseProjectOwner,
    ProjectMembershipResponse,
    ProjectJoinLeaveResponse,
    ProjectVisibilityUpdateRequest,
    ProjectVisibilityUpdateResponse,
)
from ..services.project_permissions import (
    get_project_member,
)
from ..services.project_images import build_public_image_url
from ..logging import log_event

router = APIRouter(prefix="/projects", tags=["projects"])
logger = logging.getLogger(__name__)


@router.get("/browse", response_model=BrowseProjectsResponse)
def browse_public_projects(
    category: Optional[str] = Query(None, description="Optional category filter"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List public projects with membership and member count info."""
    # Aggregate member counts
    member_counts_sq = (
        db.query(
            ProjectMember.project_id.label("project_id"),
            func.count(ProjectMember.user_id).label("member_count"),
        )
        .group_by(ProjectMember.project_id)
        .subquery()
    )

    query = (
        db.query(
            Project,
            User.name.label("owner_name"),
            User.email.label("owner_email"),
            func.coalesce(member_counts_sq.c.member_count, 0).label("member_count"),
            ProjectMember.role.label("current_user_role"),
        )
        .join(User, User.id == Project.user_id)
        .outerjoin(member_counts_sq, member_counts_sq.c.project_id == Project.id)
        .outerjoin(
            ProjectMember,
            and_(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user.id,
            ),
        )
        .filter(Project.is_public == True, Project.archived == False)
    )

    if category:
        query = query.filter(Project.category == category)

    # Order by most recently created, then name
    rows = query.order_by(Project.created_at.desc(), Project.name.asc()).all()

    project_ids = [project.id for project, *_ in rows]
    owners_map: dict[str, List[BrowseProjectOwner]] = {pid: [] for pid in project_ids}

    if project_ids:
        owner_rows = (
            db.query(
                ProjectMember.project_id,
                ProjectMember.user_id,
                User.name,
                User.email,
                ProjectMember.joined_at,
            )
            .join(User, User.id == ProjectMember.user_id)
            .filter(
                ProjectMember.project_id.in_(project_ids),
                ProjectMember.role == "owner",
            )
            .order_by(ProjectMember.project_id.asc(), ProjectMember.joined_at.asc(), User.name.asc(), User.email.asc())
            .all()
        )

        for project_id, owner_id, owner_name_value, owner_email_value, _ in owner_rows:
            project_id_str = str(project_id)
            owners_map.setdefault(project_id_str, []).append(
                BrowseProjectOwner(
                    id=str(owner_id),
                    name=owner_name_value,
                    email=owner_email_value,
                )
            )

    items: List[BrowseProjectItem] = []
    for project, owner_name, owner_email, member_count, current_user_role in rows:
        project_id_str = project.id
        project_owners = owners_map.get(project_id_str, [])
        primary_owner = project_owners[0] if project_owners else None
        image_url = build_public_image_url(project, expiry_minutes=1440, append_version=True)

        items.append(
            BrowseProjectItem(
                id=project.id,
                name=project.name,
                description=project.description,
                category=project.category,
                owner_id=primary_owner.id if primary_owner else project.user_id,
                owner_name=primary_owner.name if primary_owner and primary_owner.name else owner_name,
                owner_email=primary_owner.email if primary_owner and primary_owner.email else owner_email,
                owners=project_owners,
                public_image_url=image_url,
                public_image_updated_at=project.public_image_updated_at,
                is_public=bool(project.is_public),
                is_public_candidate=bool(project.is_public_candidate),
                member_count=int(member_count or 0),
                is_member=current_user_role is not None,
                current_user_role=current_user_role,
                created_at=project.created_at,
            )
        )

    return BrowseProjectsResponse(projects=items)


@router.get("/{project_id:uuid}/is-member", response_model=ProjectMembershipResponse)
def is_member(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pid = str(project_id)
    row = (
        db.query(Project, ProjectMember.role.label("member_role"))
        .outerjoin(
            ProjectMember,
            and_(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user.id,
            ),
        )
        .filter(Project.id == pid, Project.archived == False)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    project, member_role = row
    if not project.is_public:
        raise HTTPException(status_code=404, detail="Project not found")
    if member_role is None:
        return ProjectMembershipResponse(is_member=False, role=None)
    return ProjectMembershipResponse(is_member=True, role=member_role)


@router.post("/{project_id:uuid}/join", response_model=ProjectJoinLeaveResponse)
def join_public_project(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Join a public project. Idempotent if already a member."""
    pid = str(project_id)
    project = db.query(Project).filter(Project.id == pid, Project.archived == False).first()
    if not project or not project.is_public:
        raise HTTPException(status_code=404, detail="Project not found or not public")

    try:
        db.add(
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role="member",
            )
        )
        db.commit()
        return ProjectJoinLeaveResponse(
            message="Joined successfully",
            project_id=project.id,
            project_name=project.name,
        )
    except IntegrityError as exc:
        db.rollback()
        try:
            existing_member = get_project_member(user.id, pid, db)
        except Exception as lookup_exc:
            existing_member = None
            log_event(
                logger,
                "ERROR",
                "projects.join.integrity_recheck.failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                error_type=type(lookup_exc).__name__,
                exc_info=lookup_exc,
            )
        if existing_member:
            # Unique constraint on (project_id, user_id) preserves idempotency.
            return ProjectJoinLeaveResponse(
                message="Already a member",
                project_id=project.id,
                project_name=project.name,
            )
        log_event(
            logger,
            "ERROR",
            "projects.join.failed",
            "error",
            user_id=str(user.id),
            project_id=pid,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=500, detail="Failed to join project") from exc
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "ERROR",
            "projects.join.failed",
            "error",
            user_id=str(user.id),
            project_id=pid,
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=500, detail="Failed to join project")




@router.patch("/{project_id:uuid}/visibility", response_model=ProjectVisibilityUpdateResponse)
def set_project_visibility(
    project_id: UUID,
    payload: ProjectVisibilityUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Allow owner to toggle public visibility ONLY for projects marked as public candidates.

    Only projects created via admin panel (is_public_candidate=True) can toggle visibility.
    This applies to all users, including admins.
    When making public, requires description and category to be set.
    """
    pid = str(project_id)
    row = (
        db.query(Project, ProjectMember.role.label("member_role"))
        .outerjoin(
            ProjectMember,
            and_(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user.id,
            ),
        )
        .filter(Project.id == pid, Project.archived == False)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    project, member_role = row

    # Must be the owner (or admin for permission check)
    is_admin = (user.role or "").lower() == "admin"
    if not is_admin and member_role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be the project owner to perform this action",
        )

    # Only projects marked as public candidates can toggle visibility (applies to everyone)
    if not project.is_public_candidate:
        raise HTTPException(
            status_code=403,
            detail="This project has not been approved for public visibility. Contact an administrator."
        )

    if payload.is_public:
        if not (project.description and project.description.strip()):
            raise HTTPException(status_code=400, detail="Description is required before making a project public")
        if not (project.category and project.category.strip()):
            raise HTTPException(status_code=400, detail="Category is required before making a project public")

    try:
        project.is_public = bool(payload.is_public)
        db.commit()
        return ProjectVisibilityUpdateResponse(
            message="Updated",
            project_id=project.id,
            is_public=project.is_public or False,
        )
    except Exception as exc:
        db.rollback()
        log_event(
            logger,
            "ERROR",
            "projects.visibility_update.failed",
            "error",
            user_id=str(user.id),
            project_id=pid,
            target_visibility=bool(payload.is_public),
            error_type=type(exc).__name__,
            exc_info=exc,
        )
        raise HTTPException(status_code=500, detail="Failed to update visibility")
