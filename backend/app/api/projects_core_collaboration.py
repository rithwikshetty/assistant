from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..config.database import get_db
from ..config.settings import settings
from ..database.models import Conversation, Project, ProjectMember, ProjectShare, User
from ..schemas.projects_core import (
    ProjectJoinResponse,
    ProjectMemberResponse,
    ProjectMembersListResponse,
    ProjectMemberRoleUpdateRequest,
    ProjectOwnershipTransferResponse,
    ProjectOwnershipTransferRequest,
    ProjectShareResponse,
)
from ..services.files import file_service
from ..services.project_permissions import get_project_member, require_project_member, require_project_owner
from ..logging import log_event


logger = logging.getLogger(__name__)


def register_collaboration_routes(
    router: APIRouter,
    *,
    count_project_owners: Callable[[str, Session], int],
    assign_new_primary_owner: Callable[[Project, Session, Optional[str]], None],
    archive_project: Callable[[Session, Project, str], None],
) -> None:
    @router.post("/{project_id:uuid}/share", response_model=ProjectShareResponse)
    async def generate_project_share_link(
        project_id: UUID,
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """Generate a share link for the project. Any member can generate links."""
        pid = str(project_id)
        require_project_member(user, pid, db)

        project = db.query(Project).filter(Project.id == pid, Project.archived.is_(False)).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        now = datetime.now(timezone.utc)
        share_token = secrets.token_urlsafe(32)
        expires_at = now + timedelta(days=7)

        project_share = ProjectShare(
            project_id=pid,
            share_token=share_token,
            created_by=user.id,
            expires_at=expires_at,
        )

        try:
            db.add(project_share)
            db.commit()
            db.refresh(project_share)
            frontend_url = settings.resolve_frontend_url(request.headers.get("origin"))
            share_url = f"{frontend_url}/share/project/{share_token}"
            return ProjectShareResponse(
                share_token=share_token,
                share_url=share_url,
                expires_at=expires_at.isoformat().replace("+00:00", "Z"),
            )
        except Exception as exc:
            db.rollback()
            log_event(
                logger,
                "ERROR",
                "projects.collaboration.share_link_create.failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                error_type=type(exc).__name__,
                exc_info=exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create share link",
            ) from exc

    @router.get("/{project_id:uuid}/members", response_model=ProjectMembersListResponse)
    async def get_project_members(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """List all members of the project. Requires project membership."""
        pid = str(project_id)
        require_project_member(user, pid, db)

        members = (
            db.query(ProjectMember, User)
            .join(User, ProjectMember.user_id == User.id)
            .filter(ProjectMember.project_id == pid)
            .all()
        )

        return ProjectMembersListResponse(
            members=[
                ProjectMemberResponse(
                    user_id=member.user_id,
                    user_name=user_obj.name or user_obj.email,
                    user_email=user_obj.email,
                    role=member.role,
                    joined_at=member.joined_at,
                )
                for member, user_obj in members
            ]
        )

    @router.patch(
        "/{project_id:uuid}/members/{member_id}/role",
        response_model=ProjectMemberResponse,
    )
    async def update_project_member_role(
        project_id: UUID,
        member_id: UUID,
        payload: ProjectMemberRoleUpdateRequest,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        pid = str(project_id)
        mid = str(member_id)
        project = db.query(Project).filter(Project.id == pid, Project.archived.is_(False)).first()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        target_member = (
            db.query(ProjectMember)
            .filter(ProjectMember.project_id == pid, ProjectMember.user_id == mid)
            .first()
        )
        if not target_member:
            raise HTTPException(status_code=404, detail="Member not found")

        is_admin = (user.role or "").lower() == "admin"
        if not is_admin:
            require_project_owner(user, pid, db)

        desired_role = payload.role
        if desired_role == target_member.role:
            user_obj = db.query(User).filter(User.id == target_member.user_id).first()
            if not user_obj:
                raise HTTPException(status_code=404, detail="User record missing")
            return ProjectMemberResponse(
                user_id=target_member.user_id,
                user_name=user_obj.name or user_obj.email,
                user_email=user_obj.email,
                role=target_member.role,
                joined_at=target_member.joined_at,
            )

        if desired_role == "member":
            if target_member.role != "owner":
                raise HTTPException(status_code=400, detail="Only owners can be demoted")
            owner_count = count_project_owners(pid, db)
            if owner_count <= 1:
                raise HTTPException(status_code=400, detail="Projects must retain at least one owner")
            target_member.role = "member"
            if project.user_id == target_member.user_id:
                assign_new_primary_owner(project, db, target_member.user_id)
        else:
            target_member.role = "owner"

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            log_event(
                logger,
                "ERROR",
                "projects.collaboration.member_role_update.failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                member_id=mid,
                requested_role=desired_role,
                error_type=type(exc).__name__,
                exc_info=exc,
            )
            raise HTTPException(status_code=500, detail="Failed to update member role") from exc

        db.refresh(target_member)
        user_obj = db.query(User).filter(User.id == target_member.user_id).first()
        if not user_obj:
            raise HTTPException(status_code=404, detail="User record missing")

        return ProjectMemberResponse(
            user_id=target_member.user_id,
            user_name=user_obj.name or user_obj.email,
            user_email=user_obj.email,
            role=target_member.role,
            joined_at=target_member.joined_at,
        )

    @router.post(
        "/{project_id:uuid}/leave",
        response_model=ProjectJoinResponse,
        status_code=status.HTTP_200_OK,
    )
    async def leave_project(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """Leave a project. At least one owner must remain (or the project is deleted)."""
        pid = str(project_id)
        member = get_project_member(user.id, pid, db)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="You are not a member of this project",
            )

        total_members = db.query(ProjectMember).filter(ProjectMember.project_id == pid).count()
        project: Optional[Project] = None
        owner_count: Optional[int] = None

        if member.role == "owner":
            owner_count = count_project_owners(pid, db)
            project = db.query(Project).filter(Project.id == pid, Project.archived.is_(False)).first()
            if not project:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

            if owner_count <= 1:
                if total_members > 1:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Add another owner before leaving this project.",
                    )
                try:
                    archive_project(db, project, user.id)
                    db.delete(member)
                    db.commit()
                    file_service.purge_archived_project_blob_content_best_effort(
                        db=db,
                        project_ids=[pid],
                        user_id=str(user.id),
                    )
                    return ProjectJoinResponse(
                        message="Project deleted",
                        project_id=project.id,
                        project_name=project.name,
                    )
                except Exception as exc:
                    db.rollback()
                    log_event(
                        logger,
                        "ERROR",
                        "projects.collaboration.leave_project_delete.failed",
                        "error",
                        user_id=str(user.id),
                        project_id=pid,
                        error_type=type(exc).__name__,
                        exc_info=exc,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to delete project while leaving",
                    ) from exc

        try:
            conversations = db.query(Conversation).filter(
                Conversation.project_id == pid,
                Conversation.user_id == user.id,
                Conversation.archived.is_(False),
            ).all()
            archived_conversation_ids = [str(conv.id) for conv in conversations if getattr(conv, "id", None)]
            now = datetime.now(timezone.utc)
            for conv in conversations:
                conv.archived = True
                conv.archived_at = now
                conv.archived_by = user.id

            db.delete(member)
            if member.role == "owner" and owner_count and owner_count > 1 and project is not None:
                assign_new_primary_owner(project, db, user.id)
            db.commit()
            if archived_conversation_ids:
                file_service.purge_archived_conversation_blob_content_best_effort(
                    db=db,
                    conversation_ids=archived_conversation_ids,
                    user_id=str(user.id),
                )
            return ProjectJoinResponse(
                message="Left project successfully",
                project_id=pid,
                project_name=getattr(project, "name", None) or "",
            )
        except Exception as exc:
            db.rollback()
            log_event(
                logger,
                "ERROR",
                "projects.collaboration.leave_project.failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                error_type=type(exc).__name__,
                exc_info=exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to leave project",
            ) from exc

    @router.post(
        "/{project_id:uuid}/transfer",
        response_model=ProjectOwnershipTransferResponse,
        status_code=status.HTTP_200_OK,
    )
    async def transfer_project_ownership(
        project_id: UUID,
        transfer: ProjectOwnershipTransferRequest,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        """Transfer project ownership to another member. Only owner can do this."""
        pid = str(project_id)
        current_owner_member = get_project_member(user.id, pid, db)
        if not current_owner_member or current_owner_member.role != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be the project owner to perform this action",
            )

        new_owner_member = get_project_member(transfer.new_owner_id, pid, db)
        if not new_owner_member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New owner must be a project member",
            )

        project = db.query(Project).filter(Project.id == pid, Project.archived.is_(False)).first()
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        try:
            current_owner_member.role = "member"
            new_owner_member.role = "owner"
            project.user_id = transfer.new_owner_id
            project.updated_at = datetime.now(timezone.utc)
            db.commit()
            return ProjectOwnershipTransferResponse(
                message="Ownership transferred successfully",
                new_owner_id=transfer.new_owner_id,
            )
        except Exception as exc:
            db.rollback()
            log_event(
                logger,
                "ERROR",
                "projects.collaboration.transfer_ownership.failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                new_owner_id=str(transfer.new_owner_id),
                error_type=type(exc).__name__,
                exc_info=exc,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to transfer ownership",
            ) from exc
