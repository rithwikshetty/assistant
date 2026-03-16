from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.api.admin import _build_user_admin_response
from app.database.models import User


def test_build_user_admin_response_formats_last_login_with_single_utc_suffix() -> None:
    user = User(
        id=str(uuid4()),
        email="admin@example.com",
        name="Admin User",
        role="admin",
        is_active=True,
        created_at=datetime(2026, 3, 5, 4, 30, 0, tzinfo=timezone.utc),
        last_login_at=datetime(2026, 3, 5, 4, 31, 59, 962906, tzinfo=timezone.utc),
    )

    response = _build_user_admin_response(user, conversation_count=7, total_cost=Decimal("12.34"))

    assert response.last_login_at == "2026-03-05T04:31:59.962906Z"
