from types import SimpleNamespace

from app.services.admin.admin_service import AdminService
from app.services.feedback_service import FeedbackService


class _FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.refreshed = []

    def commit(self):  # type: ignore[no-untyped-def]
        self.commit_calls += 1
        return None

    def refresh(self, obj):  # type: ignore[no-untyped-def]
        self.refreshed.append(obj)
        return None


def test_update_user_role_rebalances_feedback_rollup_on_admin_boundary_change(monkeypatch) -> None:
    service = AdminService()
    db = _FakeSession()
    target_user = SimpleNamespace(id="user_1", role="user", is_active=True)
    acting_user = SimpleNamespace(id="admin_1")
    captured = []

    monkeypatch.setattr(service, "_get_user_or_raise", lambda db, user_id: target_user)
    monkeypatch.setattr(service, "_count_active_admins", lambda db: 2)

    def _capture(self, *, db, user_id, old_role, new_role):  # type: ignore[no-untyped-def]
        captured.append((db, user_id, old_role, new_role))

    monkeypatch.setattr(FeedbackService, "adjust_non_admin_rollup_for_role_change", _capture)

    updated = service.update_user_role(
        db=db,  # type: ignore[arg-type]
        target_user_id="user_1",
        new_role="admin",
        acting_user=acting_user,  # type: ignore[arg-type]
    )

    assert updated is target_user
    assert target_user.role == "admin"
    assert db.commit_calls == 1
    assert len(db.refreshed) == 1
    assert len(captured) == 1
    _, captured_user_id, old_role, new_role = captured[0]
    assert captured_user_id == "user_1"
    assert old_role == "user"
    assert new_role == "admin"


def test_update_user_role_skips_feedback_rollup_rebalance_when_scope_unchanged(monkeypatch) -> None:
    service = AdminService()
    db = _FakeSession()
    target_user = SimpleNamespace(id="user_2", role="user", is_active=True)
    acting_user = SimpleNamespace(id="admin_2")
    captured = []

    monkeypatch.setattr(service, "_get_user_or_raise", lambda db, user_id: target_user)
    monkeypatch.setattr(service, "_count_active_admins", lambda db: 2)

    def _capture(self, *, db, user_id, old_role, new_role):  # type: ignore[no-untyped-def]
        captured.append((db, user_id, old_role, new_role))

    monkeypatch.setattr(FeedbackService, "adjust_non_admin_rollup_for_role_change", _capture)

    updated = service.update_user_role(
        db=db,  # type: ignore[arg-type]
        target_user_id="user_2",
        new_role="user",
        acting_user=acting_user,  # type: ignore[arg-type]
    )

    assert updated is target_user
    assert db.commit_calls == 1
    assert len(captured) == 0

