from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.chat.services.event_store_service import _apply_projection


def _conversation(last_message_at):
    return SimpleNamespace(last_message_at=last_message_at)


def _state(last_message_at):
    return SimpleNamespace(
        updated_at=None,
        last_user_message_id=None,
        last_assistant_message_id=None,
        last_user_preview=None,
        awaiting_user_input=False,
    )


def _message(*, created_at: datetime, role: str = "user", status: str = "completed", text: str = "hello"):
    return SimpleNamespace(
        id="msg_1",
        role=role,
        status=status,
        text=text,
        created_at=created_at,
    )


def test_apply_projection_does_not_regress_last_message_at_for_backfilled_messages() -> None:
    now = datetime.now(timezone.utc)
    older = now - timedelta(days=30)
    conversation = _conversation(last_message_at=now)
    state = _state(last_message_at=now)

    _apply_projection(
        conversation=conversation,
        state=state,
        message=_message(created_at=older, text="old branch seed"),
        metadata_part={"event_type": "user_message"},
    )

    assert conversation.last_message_at == older

def test_apply_projection_advances_last_message_at_for_newer_messages() -> None:
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    newer = start + timedelta(minutes=6)
    conversation = _conversation(last_message_at=start)
    state = _state(last_message_at=start)

    _apply_projection(
        conversation=conversation,
        state=state,
        message=_message(created_at=newer, text="new message"),
        metadata_part={"event_type": "user_message"},
    )

    assert conversation.last_message_at == newer

def test_apply_projection_handles_naive_and_aware_datetimes_without_crashing() -> None:
    aware_now = datetime.now(timezone.utc)
    naive_older = (aware_now - timedelta(days=1)).replace(tzinfo=None)
    conversation = _conversation(last_message_at=aware_now)
    state = _state(last_message_at=aware_now)

    _apply_projection(
        conversation=conversation,
        state=state,
        message=_message(created_at=naive_older, text="legacy-naive-message"),
        metadata_part={"event_type": "user_message"},
    )

    assert conversation.last_message_at == naive_older
