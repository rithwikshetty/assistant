from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import project_permissions as permissions


class _SyncMembershipQueryStub:
    def __init__(self, result) -> None:
        self._result = result

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def join(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):
        return self._result


class _SyncDBStub:
    def __init__(self, *, member_exists: bool) -> None:
        self.member_exists = member_exists
        self.query_calls = []

    def query(self, *entities):  # noqa: ANN002
        self.query_calls.append(entities)
        result = object() if self.member_exists else None
        return _SyncMembershipQueryStub(result)


class _AsyncDBStub:
    def __init__(self, scalar_result) -> None:
        self.scalar_result = scalar_result

    async def scalar(self, _stmt):  # noqa: ANN001
        return self.scalar_result


def test_can_access_conversation_owner_short_circuits_without_query() -> None:
    user = SimpleNamespace(id="user_1", role="user")
    conversation = SimpleNamespace(user_id="user_1", project_id="proj_1")
    db = _SyncDBStub(member_exists=False)

    assert permissions.can_access_conversation(user, conversation, db) is True
    assert db.query_calls == []


def test_can_access_conversation_admin_short_circuits_without_query() -> None:
    user = SimpleNamespace(id="admin_1", role="admin")
    conversation = SimpleNamespace(user_id="other_user", project_id="proj_1")
    db = _SyncDBStub(member_exists=False)

    assert permissions.can_access_conversation(user, conversation, db) is True
    assert db.query_calls == []


def test_can_access_conversation_uses_single_membership_query_for_project_member() -> None:
    user = SimpleNamespace(id="user_2", role="user")
    conversation = SimpleNamespace(user_id="owner_2", project_id="proj_2")
    db = _SyncDBStub(member_exists=True)

    assert permissions.can_access_conversation(user, conversation, db) is True
    assert len(db.query_calls) == 1
    assert db.query_calls[0] == (permissions.Project.id,)


def test_can_access_conversation_returns_false_without_project_id() -> None:
    user = SimpleNamespace(id="user_3", role="user")
    conversation = SimpleNamespace(user_id="owner_3", project_id=None)
    db = _SyncDBStub(member_exists=True)

    assert permissions.can_access_conversation(user, conversation, db) is False
    assert db.query_calls == []


@pytest.mark.asyncio
async def test_can_access_conversation_async_returns_true_for_member() -> None:
    user = SimpleNamespace(id="user_4", role="user")
    conversation = SimpleNamespace(user_id="owner_4", project_id="proj_4")
    db = _AsyncDBStub(scalar_result="proj_4")

    assert await permissions.can_access_conversation_async(user, conversation, db) is True


@pytest.mark.asyncio
async def test_can_access_conversation_async_returns_false_when_membership_missing() -> None:
    user = SimpleNamespace(id="user_5", role="user")
    conversation = SimpleNamespace(user_id="owner_5", project_id="proj_5")
    db = _AsyncDBStub(scalar_result=None)

    assert await permissions.can_access_conversation_async(user, conversation, db) is False
