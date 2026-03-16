from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

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
