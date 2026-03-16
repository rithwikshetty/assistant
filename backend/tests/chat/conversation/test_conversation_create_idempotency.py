from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.chat.routes import conversations
from app.chat.schemas import CreateConversationRequest
from app.utils.integrity import is_constraint_violation


class _FakeDiag:
    def __init__(self, constraint_name: str | None) -> None:
        self.constraint_name = constraint_name


class _FakeOrigError(Exception):
    def __init__(self, message: str, constraint_name: str | None = None) -> None:
        super().__init__(message)
        self.diag = _FakeDiag(constraint_name)


class _FakeDB:
    def __init__(self, commit_exc: Exception | None = None) -> None:
        self._commit_exc = commit_exc
        self.rollback_calls = 0
        self.refresh_calls = 0
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        if self._commit_exc is not None:
            raise self._commit_exc

    def rollback(self) -> None:
        self.rollback_calls += 1

    def refresh(self, obj: object) -> None:
        _ = obj
        self.refresh_calls += 1

    def query(self, *args, **kwargs):  # pragma: no cover - should not be called in these tests
        _ = (args, kwargs)
        raise AssertionError("Unexpected query() call in idempotency unit test")


def _make_integrity_error(message: str, constraint_name: str | None = None) -> IntegrityError:
    return IntegrityError(
        statement="INSERT ...",
        params={},
        orig=_FakeOrigError(message, constraint_name=constraint_name),
    )


def test_create_idempotency_conflict_true_for_known_constraint_name() -> None:
    exc = _make_integrity_error("duplicate key", "uq_conversations_user_creation_request")
    assert is_constraint_violation(exc, conversations._CONVERSATION_CREATE_IDEMPOTENCY_CONSTRAINTS) is True


def test_create_idempotency_conflict_true_when_constraint_name_is_in_message() -> None:
    exc = _make_integrity_error(
        'duplicate key value violates unique constraint "uq_conversations_user_creation_request"',
        constraint_name=None,
    )
    assert is_constraint_violation(exc, conversations._CONVERSATION_CREATE_IDEMPOTENCY_CONSTRAINTS) is True


def test_create_idempotency_conflict_false_for_non_idempotency_constraint() -> None:
    exc = _make_integrity_error("duplicate key", "uq_messages_conversation_created")
    assert is_constraint_violation(exc, conversations._CONVERSATION_CREATE_IDEMPOTENCY_CONSTRAINTS) is False


def test_create_conversation_reuses_existing_when_commit_hits_idempotency_conflict(monkeypatch) -> None:
    request_id = "req_123"
    existing_conversation = SimpleNamespace(id="conv_existing", archived=False)
    calls: list[tuple[str, str]] = []

    def fake_check_conversation_idempotency(incoming_request_id: str, user_id: str, db: object):
        _ = db
        calls.append((incoming_request_id, user_id))
        if len(calls) == 1:
            return None
        return existing_conversation

    monkeypatch.setattr(conversations, "check_conversation_idempotency", fake_check_conversation_idempotency)
    monkeypatch.setattr(conversations, "build_conversation_response", lambda conv, db, current_user=None, **kwargs: {"id": conv.id})
    monkeypatch.setattr(conversations.analytics_event_recorder, "record_new_conversation", lambda db, user_id: None)

    fake_db = _FakeDB(
        commit_exc=_make_integrity_error(
            "duplicate key",
            constraint_name="uq_conversations_user_creation_request",
        )
    )
    current_user = SimpleNamespace(id="user_123", name="Test User", email="test@example.com")
    payload = CreateConversationRequest(request_id=request_id, title="New Chat")

    response = conversations.create_conversation(
        payload=payload,
        current_user=current_user,
        db=fake_db,
    )

    assert response == {"id": "conv_existing"}
    assert calls == [(request_id, "user_123"), (request_id, "user_123")]
    assert fake_db.rollback_calls == 1
    assert fake_db.refresh_calls == 0


def test_create_conversation_returns_409_when_idempotency_conflict_cannot_be_reused(monkeypatch) -> None:
    request_id = "req_456"

    def fake_check_conversation_idempotency(incoming_request_id: str, user_id: str, db: object):
        _ = (incoming_request_id, user_id, db)
        return None

    monkeypatch.setattr(conversations, "check_conversation_idempotency", fake_check_conversation_idempotency)
    monkeypatch.setattr(conversations.analytics_event_recorder, "record_new_conversation", lambda db, user_id: None)

    fake_db = _FakeDB(
        commit_exc=_make_integrity_error(
            "duplicate key",
            constraint_name="uq_conversations_user_creation_request",
        )
    )
    current_user = SimpleNamespace(id="user_123", name="Test User", email="test@example.com")
    payload = CreateConversationRequest(request_id=request_id, title="New Chat")

    with pytest.raises(HTTPException) as exc:
        conversations.create_conversation(
            payload=payload,
            current_user=current_user,
            db=fake_db,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Duplicate conversation request for this user"
    assert fake_db.rollback_calls == 1


def test_create_conversation_reuses_existing_when_client_supplies_known_conversation_id(monkeypatch) -> None:
    existing_conversation = SimpleNamespace(id="conv_existing", archived=False)

    monkeypatch.setattr(
        conversations,
        "find_conversation_for_owner_by_id",
        lambda **kwargs: existing_conversation,
    )
    monkeypatch.setattr(
        conversations,
        "build_conversation_response",
        lambda conv, db, current_user=None, **kwargs: {"id": conv.id, "source": "existing"},
    )
    monkeypatch.setattr(conversations.analytics_event_recorder, "record_new_conversation", lambda db, user_id: None)

    fake_db = _FakeDB()
    current_user = SimpleNamespace(id="user_123", name="Test User", email="test@example.com")
    payload = CreateConversationRequest(
        conversation_id="11111111-1111-4111-8111-111111111111",
        request_id="req_789",
        title="New Chat",
    )

    response = conversations.create_conversation(
        payload=payload,
        current_user=current_user,
        db=fake_db,
    )

    assert response == {"id": "conv_existing", "source": "existing"}
    assert fake_db.added == []
    assert fake_db.rollback_calls == 0


def test_create_conversation_reuses_existing_after_client_id_conflict(monkeypatch) -> None:
    existing_conversation = SimpleNamespace(id="conv_existing", archived=False)

    def fake_find_conversation_for_owner_by_id(**kwargs):
        _ = kwargs
        fake_find_conversation_for_owner_by_id.calls += 1
        if fake_find_conversation_for_owner_by_id.calls == 1:
            return None
        return existing_conversation

    fake_find_conversation_for_owner_by_id.calls = 0

    monkeypatch.setattr(
        conversations,
        "find_conversation_for_owner_by_id",
        fake_find_conversation_for_owner_by_id,
    )
    monkeypatch.setattr(
        conversations,
        "check_conversation_idempotency",
        lambda request_id, user_id, db: None,
    )
    monkeypatch.setattr(
        conversations,
        "build_conversation_response",
        lambda conv, db, current_user=None, **kwargs: {"id": conv.id, "source": "conflict_reuse"},
    )
    monkeypatch.setattr(conversations.analytics_event_recorder, "record_new_conversation", lambda db, user_id: None)

    fake_db = _FakeDB(commit_exc=_make_integrity_error("duplicate key", constraint_name="conversations_pkey"))
    current_user = SimpleNamespace(id="user_123", name="Test User", email="test@example.com")
    payload = CreateConversationRequest(
        conversation_id="22222222-2222-4222-8222-222222222222",
        title="New Chat",
    )

    response = conversations.create_conversation(
        payload=payload,
        current_user=current_user,
        db=fake_db,
    )

    assert response == {"id": "conv_existing", "source": "conflict_reuse"}
    assert fake_db.rollback_calls == 1
