from sqlalchemy.exc import IntegrityError

from app.chat.services import submit_runtime_service


class _FakeDiag:
    def __init__(self, constraint_name: str | None) -> None:
        self.constraint_name = constraint_name


class _FakeOrigError(Exception):
    def __init__(self, message: str, constraint_name: str | None = None) -> None:
        super().__init__(message)
        self.diag = _FakeDiag(constraint_name)


def _make_integrity_error(message: str, constraint_name: str | None = None) -> IntegrityError:
    return IntegrityError(
        statement="INSERT ...",
        params={},
        orig=_FakeOrigError(message, constraint_name=constraint_name),
    )


def test_idempotency_conflict_true_for_known_constraint_name() -> None:
    exc = _make_integrity_error("duplicate key", "uq_chat_runs_conversation_request")
    assert submit_runtime_service._is_idempotency_conflict(exc) is True


def test_idempotency_conflict_true_when_constraint_name_is_in_message() -> None:
    exc = _make_integrity_error(
        'duplicate key value violates unique constraint "uq_chat_runs_conversation_user_message"',
        constraint_name=None,
    )
    assert submit_runtime_service._is_idempotency_conflict(exc) is True


def test_idempotency_conflict_false_for_non_idempotency_constraint() -> None:
    exc = _make_integrity_error("duplicate key", "uq_message_parts_message_ordinal")
    assert submit_runtime_service._is_idempotency_conflict(exc) is False
