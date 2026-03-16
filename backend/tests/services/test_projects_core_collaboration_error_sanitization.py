from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api import projects_core_collaboration as collaboration


class _Query:
    def __init__(self, value):
        self._value = value

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):
        return self._value


class _DB:
    def __init__(self, project, *, commit_error: Exception):
        self._project = project
        self._commit_error = commit_error

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is collaboration.Project:
            return _Query(self._project)
        raise AssertionError(f"Unexpected model queried: {model}")

    def add(self, _value):
        return None

    def commit(self):
        raise self._commit_error

    def rollback(self):
        return None

    def refresh(self, _value):
        return None


@pytest.fixture
def project() -> SimpleNamespace:
    return SimpleNamespace(id="project-1", archived=False, name="Project One", user_id="user-1")


def _build_client(monkeypatch: pytest.MonkeyPatch, db: _DB) -> TestClient:
    router = APIRouter(prefix="/projects")
    collaboration.register_collaboration_routes(
        router,
        count_project_owners=lambda *_args, **_kwargs: 2,
        assign_new_primary_owner=lambda *_args, **_kwargs: None,
        archive_project=lambda *_args, **_kwargs: None,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[collaboration.get_current_user] = lambda: SimpleNamespace(id="user-1", role="owner")
    app.dependency_overrides[collaboration.get_db] = lambda: db

    monkeypatch.setattr(collaboration, "require_project_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(collaboration, "require_project_owner", lambda *_args, **_kwargs: None)

    return TestClient(app, raise_server_exceptions=False)


def test_generate_share_link_masks_internal_error(monkeypatch: pytest.MonkeyPatch, project: SimpleNamespace) -> None:
    client = _build_client(monkeypatch, _DB(project, commit_error=RuntimeError("secret-share-token-leaked")))

    response = client.post("/projects/00000000-0000-0000-0000-000000000001/share")

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to create share link"


def test_transfer_ownership_masks_internal_error(monkeypatch: pytest.MonkeyPatch, project: SimpleNamespace) -> None:
    client = _build_client(monkeypatch, _DB(project, commit_error=RuntimeError("db-password-leaked")))

    def _get_project_member(user_id, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        if user_id == "new-owner-id":
            return SimpleNamespace(role="member")
        return SimpleNamespace(role="owner")

    monkeypatch.setattr(collaboration, "get_project_member", _get_project_member)

    response = client.post(
        "/projects/00000000-0000-0000-0000-000000000001/transfer",
        json={"new_owner_id": "new-owner-id"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to transfer ownership"


def test_transfer_ownership_requires_owner_role(monkeypatch: pytest.MonkeyPatch, project: SimpleNamespace) -> None:
    client = _build_client(monkeypatch, _DB(project, commit_error=RuntimeError("unused")))

    def _get_project_member(user_id, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        if user_id == "new-owner-id":
            return SimpleNamespace(role="member")
        return SimpleNamespace(role="member")

    monkeypatch.setattr(collaboration, "get_project_member", _get_project_member)

    response = client.post(
        "/projects/00000000-0000-0000-0000-000000000001/transfer",
        json={"new_owner_id": "new-owner-id"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "You must be the project owner to perform this action"
