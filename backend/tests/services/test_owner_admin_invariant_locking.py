"""LAT-005: Verify owner/admin invariant checks use FOR UPDATE locking."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional


class _TrackingQuery:
    """Records whether with_for_update() was called during query chain."""

    def __init__(self, results: Optional[List[Any]] = None) -> None:
        self._results = results or []
        self.for_update_called = False

    def filter(self, *args, **kwargs) -> "_TrackingQuery":
        return self

    def with_for_update(self, **kwargs) -> "_TrackingQuery":
        self.for_update_called = True
        return self

    def all(self) -> List[Any]:
        return list(self._results)

    def scalar(self) -> int:
        return len(self._results)

    def first(self) -> Any:
        return self._results[0] if self._results else None

    def count(self) -> int:
        return len(self._results)


class _FakeSession:
    """Minimal session that records FOR UPDATE usage per model class."""

    def __init__(self, *, results_by_model: Optional[dict] = None) -> None:
        self._results_by_model = results_by_model or {}
        self.queries: List[_TrackingQuery] = []
        self._model_queries: dict = {}

    def query(self, model_class: Any, *extra) -> _TrackingQuery:
        name = getattr(model_class, "__name__", str(model_class))
        results = self._results_by_model.get(name, [])
        q = _TrackingQuery(results=results)
        self.queries.append(q)
        self._model_queries.setdefault(name, []).append(q)
        return q

    def commit(self) -> None:
        pass

    def refresh(self, obj: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# LAT-005a: Project owner count must use FOR UPDATE
# ---------------------------------------------------------------------------

def test_count_project_owners_uses_for_update() -> None:
    """_count_project_owners must lock owner rows with FOR UPDATE."""
    from app.api.projects_core import _count_project_owners
    from app.database.models import ProjectMember

    owner1 = SimpleNamespace(id="m1", project_id="p1", role="owner")
    owner2 = SimpleNamespace(id="m2", project_id="p1", role="owner")

    session = _FakeSession(results_by_model={"ProjectMember": [owner1, owner2]})
    count = _count_project_owners("p1", session)

    assert count == 2
    pm_queries = session._model_queries.get("ProjectMember", [])
    assert len(pm_queries) >= 1
    assert pm_queries[0].for_update_called is True, (
        "LAT-005: _count_project_owners must use with_for_update() to prevent concurrent demotions"
    )


def test_count_project_owners_returns_zero_when_empty() -> None:
    from app.api.projects_core import _count_project_owners

    session = _FakeSession(results_by_model={"ProjectMember": []})
    count = _count_project_owners("p1", session)

    assert count == 0


# ---------------------------------------------------------------------------
# LAT-005b: Active admin count must use FOR UPDATE
# ---------------------------------------------------------------------------

def test_count_active_admins_uses_for_update() -> None:
    """AdminService._count_active_admins must lock admin rows with FOR UPDATE."""
    from app.services.admin.admin_service import AdminService
    from app.database.models import User

    admin1 = SimpleNamespace(id="u1", role="admin", is_active=True)
    admin2 = SimpleNamespace(id="u2", role="admin", is_active=True)

    session = _FakeSession(results_by_model={"User": [admin1, admin2]})
    svc = AdminService()
    count = svc._count_active_admins(session)

    assert count == 2
    user_queries = session._model_queries.get("User", [])
    assert len(user_queries) >= 1
    assert user_queries[0].for_update_called is True, (
        "LAT-005: _count_active_admins must use with_for_update() to prevent concurrent demotions"
    )


def test_count_active_admins_returns_zero_when_empty() -> None:
    from app.services.admin.admin_service import AdminService

    session = _FakeSession(results_by_model={"User": []})
    svc = AdminService()
    count = svc._count_active_admins(session)

    assert count == 0
