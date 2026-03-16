from fastapi import HTTPException, status

from ..database.models import User


def ensure_user_has_app_access(user: User) -> None:
    """Raise access denied when a user account is disabled."""
    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="access_denied",
            headers={"X-Access-Denied": "true"},
        )
