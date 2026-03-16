from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..database.models import User
from .dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["authentication"])


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    user_tier: str = "power"
    last_login_at: str | None = None
    last_login_country: str | None = None


@router.get("/me", response_model=UserResponse)
async def get_workspace_user(
    user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=str(user.email or "").strip(),
        name=str(user.name or "").strip() or "assistant",
        role=str(user.role or "user").strip() or "user",
        user_tier=str(user.user_tier or "power").strip() or "power",
        last_login_at=user.last_login_at.isoformat() if getattr(user, "last_login_at", None) else None,
        last_login_country=getattr(user, "last_login_country", None),
    )
