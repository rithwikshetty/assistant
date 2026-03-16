from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api import projects as projects_api
from app.api import share as share_api


class _QueryStub:
    def __init__(self, result):
        self._result = result

    def outerjoin(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):
        return self._result


class _ProjectsJoinDBStub:
    def __init__(
        self,
        *,
        project,
        commit_error: Exception | None = None,
        membership_result=None,
        project_role: str | None = None,
    ) -> None:
        self._project = project
        self._commit_error = commit_error
        self._membership_result = membership_result
        self._project_role = project_role
        self.added = []
        self.rollback_calls = 0
        self.project_member_query_calls = 0

    def query(self, model, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if model is projects_api.Project:
            if args:
                return _QueryStub((self._project, self._project_role))
            return _QueryStub(self._project)
        if model is projects_api.ProjectMember:
            self.project_member_query_calls += 1
            return _QueryStub(self._membership_result)
        return _QueryStub(None)

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error

    def rollback(self) -> None:
        self.rollback_calls += 1


class _ShareJoinDBStub:
    def __init__(
        self,
        *,
        share,
        project,
        commit_error: Exception | None = None,
        membership_result=None,
    ) -> None:
        self._share = share
        self._project = project
        self._commit_error = commit_error
        self._membership_result = membership_result
        self.added = []
        self.rollback_calls = 0
        self.project_member_query_calls = 0

    def query(self, model, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if model is share_api.ProjectShare:
            return _QueryStub(self._share)
        if model is share_api.Project:
            return _QueryStub(self._project)
        if model is share_api.ProjectMember:
            self.project_member_query_calls += 1
            return _QueryStub(self._membership_result)
        return _QueryStub(None)

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error

    def rollback(self) -> None:
        self.rollback_calls += 1


def test_join_public_project_inserts_membership_without_precheck_query() -> None:
    user = SimpleNamespace(id="user_1")
    project = SimpleNamespace(id="proj_1", name="Alpha", is_public=True)
    db = _ProjectsJoinDBStub(project=project)

    response = projects_api.join_public_project(
        UUID("00000000-0000-0000-0000-000000000001"),
        user=user,
        db=db,
    )

    assert response.message == "Joined successfully"
    assert len(db.added) == 1
    assert db.added[0].project_id == "proj_1"
    assert db.added[0].user_id == "user_1"
    assert db.project_member_query_calls == 0


def test_join_public_project_returns_already_member_on_integrity_error() -> None:
    user = SimpleNamespace(id="user_2")
    project = SimpleNamespace(id="proj_2", name="Beta", is_public=True)
    db = _ProjectsJoinDBStub(
        project=project,
        commit_error=IntegrityError("insert", {}, Exception("duplicate")),
        membership_result=SimpleNamespace(role="member"),
    )

    response = projects_api.join_public_project(
        UUID("00000000-0000-0000-0000-000000000002"),
        user=user,
        db=db,
    )

    assert response.message == "Already a member"
    assert db.rollback_calls == 1
    assert db.project_member_query_calls == 1


def test_join_public_project_raises_on_non_duplicate_integrity_error() -> None:
    user = SimpleNamespace(id="user_2b")
    project = SimpleNamespace(id="proj_2b", name="Beta 2", is_public=True)
    db = _ProjectsJoinDBStub(
        project=project,
        commit_error=IntegrityError("insert", {}, Exception("fk violation")),
        membership_result=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        projects_api.join_public_project(
            UUID("00000000-0000-0000-0000-000000000012"),
            user=user,
            db=db,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to join project"
    assert db.rollback_calls == 1
    assert db.project_member_query_calls == 1


def test_join_project_via_share_link_returns_already_member_on_integrity_error() -> None:
    user = SimpleNamespace(id="user_3")
    share = SimpleNamespace(id="share_1", share_token="token_1", project_id="proj_3", expires_at=None)
    project = SimpleNamespace(id="proj_3", name="Gamma")
    db = _ShareJoinDBStub(
        share=share,
        project=project,
        commit_error=IntegrityError("insert", {}, Exception("duplicate")),
        membership_result=SimpleNamespace(role="member"),
    )

    response = share_api.join_project_via_share_link("token_1", current_user=user, db=db)

    assert response.message == "You are already a member of this project"
    assert db.rollback_calls == 1
    assert db.project_member_query_calls == 1


def test_join_project_via_share_link_raises_on_non_duplicate_integrity_error() -> None:
    user = SimpleNamespace(id="user_3b")
    share = SimpleNamespace(id="share_1b", share_token="token_1b", project_id="proj_3b", expires_at=None)
    project = SimpleNamespace(id="proj_3b", name="Gamma 2")
    db = _ShareJoinDBStub(
        share=share,
        project=project,
        commit_error=IntegrityError("insert", {}, Exception("fk violation")),
        membership_result=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        share_api.join_project_via_share_link("token_1b", current_user=user, db=db)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to join project"
    assert db.rollback_calls == 1
    assert db.project_member_query_calls == 1


def test_join_public_project_masks_internal_failure_details() -> None:
    user = SimpleNamespace(id="user_9")
    project = SimpleNamespace(id="proj_9", name="Delta", is_public=True)
    db = _ProjectsJoinDBStub(project=project, commit_error=RuntimeError("secret connection string"))

    with pytest.raises(HTTPException) as exc_info:
        projects_api.join_public_project(
            UUID("00000000-0000-0000-0000-000000000009"),
            user=user,
            db=db,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to join project"
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_set_project_visibility_masks_internal_failure_details() -> None:
    user = SimpleNamespace(id="admin_1", role="admin")
    project = SimpleNamespace(
        id="proj_10",
        name="Echo",
        is_public=True,
        is_public_candidate=True,
        description="desc",
        category="cat",
    )
    db = _ProjectsJoinDBStub(project=project, commit_error=RuntimeError("db write failed"))

    with pytest.raises(HTTPException) as exc_info:
        await projects_api.set_project_visibility(
            UUID("00000000-0000-0000-0000-000000000010"),
            payload=projects_api.ProjectVisibilityUpdateRequest(is_public=False),
            user=user,
            db=db,
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to update visibility"
    assert db.rollback_calls == 1


@pytest.mark.asyncio
async def test_set_project_visibility_blocks_non_owner_without_membership_query() -> None:
    user = SimpleNamespace(id="member_1", role="user")
    project = SimpleNamespace(
        id="proj_13",
        name="Hotel",
        is_public=False,
        is_public_candidate=True,
        description="desc",
        category="cat",
    )
    db = _ProjectsJoinDBStub(project=project, project_role="member")

    with pytest.raises(HTTPException) as exc_info:
        await projects_api.set_project_visibility(
            UUID("00000000-0000-0000-0000-000000000013"),
            payload=projects_api.ProjectVisibilityUpdateRequest(is_public=True),
            user=user,
            db=db,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "You must be the project owner to perform this action"
    assert db.project_member_query_calls == 0


def test_is_member_returns_role_without_project_member_lookup() -> None:
    user = SimpleNamespace(id="member_2", role="user")
    project = SimpleNamespace(id="proj_14", is_public=True)
    db = _ProjectsJoinDBStub(project=project, project_role="owner")

    response = projects_api.is_member(
        UUID("00000000-0000-0000-0000-000000000014"),
        user=user,
        db=db,
    )

    assert response.is_member is True
    assert response.role == "owner"
    assert db.project_member_query_calls == 0


def test_join_project_via_share_link_masks_internal_failure_details() -> None:
    user = SimpleNamespace(id="user_11")
    share = SimpleNamespace(id="share_11", share_token="token_11", project_id="proj_11", expires_at=None)
    project = SimpleNamespace(id="proj_11", name="Foxtrot")
    db = _ShareJoinDBStub(share=share, project=project, commit_error=RuntimeError("driver timeout"))

    with pytest.raises(HTTPException) as exc_info:
        share_api.join_project_via_share_link("token_11", current_user=user, db=db)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to join project"
    assert db.rollback_calls == 1


def test_join_project_via_share_link_does_not_log_raw_share_token(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(id="user_12")
    share = SimpleNamespace(id="share_12", share_token="token_12", project_id="proj_12", expires_at=None)
    project = SimpleNamespace(id="proj_12", name="Golf")
    db = _ShareJoinDBStub(share=share, project=project, commit_error=RuntimeError("driver timeout"))
    captured = {}

    def _capture_log_event(_logger, _level, _event_name, _kind, **kwargs):  # noqa: ANN001
        captured.update(kwargs)

    monkeypatch.setattr(share_api, "log_event", _capture_log_event)

    with pytest.raises(HTTPException):
        share_api.join_project_via_share_link("token_12", current_user=user, db=db)

    assert "share_token" not in captured
    assert captured["share_id"] == "share_12"
