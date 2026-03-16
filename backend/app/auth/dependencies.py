from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_async_db
from ..database.models import User
from ..utils.roles import normalize_role, normalize_role_set
from .local_user import get_or_create_local_user_async

async def get_current_user(
    db: AsyncSession = Depends(get_async_db)
) -> User:
    """Return the singleton local workspace user for this deployment."""
    return await get_or_create_local_user_async(db)


def require_roles(*roles: str):
    """Dependency factory to require one of the specified roles.

    Usage:
        @router.get("/admin", dependencies=[Depends(require_roles("admin"))])
    """
    allowed_roles = normalize_role_set(roles)

    async def _guard(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if normalize_role(current_user.role) not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _guard


# Convenience alias for admin-only endpoints
admin_required = require_roles("admin")
