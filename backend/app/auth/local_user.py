from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import settings
from ..database.models import User
from ..logging import bind_log_context
from .access import ensure_user_has_app_access


def _normalized_local_user_profile() -> dict[str, str]:
    email = str(getattr(settings, "local_user_email", "assistant@local") or "assistant@local").strip().lower()
    if "@" not in email:
        email = "assistant@local"

    name = str(getattr(settings, "local_user_name", "assistant") or "assistant").strip() or "assistant"
    department = str(getattr(settings, "local_user_department", "Local") or "Local").strip() or "Local"
    role = str(getattr(settings, "local_user_role", "user") or "user").strip().lower() or "user"
    user_tier = str(getattr(settings, "local_user_tier", "power") or "power").strip().lower() or "power"

    if role not in {"user", "admin"}:
        role = "user"
    if user_tier not in {"default", "power"}:
        user_tier = "power"

    return {
        "email": email,
        "name": name,
        "department": department,
        "role": role,
        "user_tier": user_tier,
    }


async def get_or_create_local_user_async(db: AsyncSession) -> User:
    profile = _normalized_local_user_profile()
    user = await db.scalar(select(User).where(User.email == profile["email"]))

    changed = False
    if user is None:
        user = User(
            email=profile["email"],
            name=profile["name"],
            department=profile["department"],
            role=profile["role"],
            user_tier=profile["user_tier"],
            is_active=True,
        )
        db.add(user)
        changed = True
    else:
        for field_name in ("name", "department", "role", "user_tier"):
            desired = profile[field_name]
            if getattr(user, field_name, None) != desired:
                setattr(user, field_name, desired)
                changed = True
        if not bool(getattr(user, "is_active", True)):
            user.is_active = True
            changed = True

    if changed:
        await db.commit()
        await db.refresh(user)

    ensure_user_has_app_access(user)
    bind_log_context(user_id=str(user.id))
    return user
