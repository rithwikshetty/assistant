"""Project permission helpers and access control."""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..database.models import Conversation, Project, ProjectMember, User
from ..utils.coerce import normalize_uuid_string


def _normalize_conversation_id_or_404(conversation_id: str) -> str:
    normalized_conversation_id = normalize_uuid_string(conversation_id)
    if normalized_conversation_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return normalized_conversation_id


def is_project_member(user_id: str, project_id: str, db: Session) -> bool:
    """Check if user is a member of the project."""
    return (
        db.query(ProjectMember.id)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        .first()
        is not None
    )


async def is_project_member_async(user_id: str, project_id: str, db: AsyncSession) -> bool:
    """Async variant of project membership check."""
    row = await db.scalar(
        select(ProjectMember.id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        .limit(1)
    )
    return row is not None


def is_project_owner(user_id: str, project_id: str, db: Session) -> bool:
    """Check if user is the project owner."""
    return (
        db.query(ProjectMember.id)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.role == "owner",
        )
        .first()
        is not None
    )


async def is_project_owner_async(user_id: str, project_id: str, db: AsyncSession) -> bool:
    """Async variant of project ownership check."""
    row = await db.scalar(
        select(ProjectMember.id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
            ProjectMember.role == "owner",
        )
        .limit(1)
    )
    return row is not None


def get_project_member(user_id: str, project_id: str, db: Session) -> Optional[ProjectMember]:
    """Get project member record."""
    return (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        .first()
    )


async def get_project_member_async(user_id: str, project_id: str, db: AsyncSession) -> Optional[ProjectMember]:
    """Async variant of project member lookup."""
    return await db.scalar(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )


def require_project_member(user: User, project_id: str, db: Session) -> None:
    """Raise 403 if user is not a project member."""
    if not is_project_member(user.id, project_id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )


async def require_project_member_async(user: User, project_id: str, db: AsyncSession) -> None:
    """Async variant of project-member guard."""
    if not await is_project_member_async(user.id, project_id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )


def require_project_owner(user: User, project_id: str, db: Session) -> None:
    """Raise 403 if user is not the project owner."""
    if not is_project_owner(user.id, project_id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be the project owner to perform this action",
        )


async def require_project_owner_async(user: User, project_id: str, db: AsyncSession) -> None:
    """Async variant of project-owner guard."""
    if not await is_project_owner_async(user.id, project_id, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be the project owner to perform this action",
        )


def require_conversation_owner(user: User, conversation_id: str, db: Session) -> Conversation:
    """Raise 404/403 if user does not own the conversation."""
    normalized_conversation_id = _normalize_conversation_id_or_404(conversation_id)
    conversation = db.query(Conversation).filter(Conversation.id == normalized_conversation_id).first()

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if conversation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot edit conversations you don't own",
        )

    return conversation


async def require_conversation_owner_async(
    user: User,
    conversation_id: str,
    db: AsyncSession,
) -> Conversation:
    """Async variant of conversation ownership guard."""
    normalized_conversation_id = _normalize_conversation_id_or_404(conversation_id)
    conversation = await db.scalar(select(Conversation).where(Conversation.id == normalized_conversation_id))

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if conversation.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot edit conversations you don't own",
        )

    return conversation


def can_access_conversation(user: User, conversation: Conversation, db: Session) -> bool:
    """Check if user can view a conversation (owner or project member)."""
    # Owner always has access
    if conversation.user_id == user.id:
        return True

    # Allow platform admins to access for moderation purposes
    user_role = (user.role or "").lower()
    if user_role == "admin":
        return True

    project_id = getattr(conversation, "project_id", None)
    if not project_id:
        return False

    membership = (
        db.query(Project.id)
        .join(
            ProjectMember,
            and_(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user.id,
            ),
        )
        .filter(
            Project.id == project_id,
            Project.archived.is_(False),
            Project.is_public_candidate.is_(False),
        )
        .first()
    )
    return membership is not None


async def can_access_conversation_async(user: User, conversation: Conversation, db: AsyncSession) -> bool:
    """Async variant of conversation access check."""
    if conversation.user_id == user.id:
        return True

    user_role = (user.role or "").lower()
    if user_role == "admin":
        return True

    project_id = getattr(conversation, "project_id", None)
    if not project_id:
        return False

    membership = await db.scalar(
        select(Project.id)
        .join(
            ProjectMember,
            and_(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user.id,
            ),
        )
        .where(
            Project.id == project_id,
            Project.archived.is_(False),
            Project.is_public_candidate.is_(False),
        )
        .limit(1)
    )
    return membership is not None
