from datetime import datetime, timezone
from types import SimpleNamespace

from app.api import share as share_api


class _ConversationQuery:
    def __init__(self, conversation):
        self._conversation = conversation

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):
        return self._conversation


class _MessageQuery:
    def __init__(self, messages):
        self._messages = messages

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):
        return list(self._messages)


class _DBStub:
    def __init__(self, conversation, messages):
        self._conversation = conversation
        self._messages = messages
        self.added = []

    def query(self, model, *args, **kwargs):  # noqa: ANN002, ANN003
        if model is share_api.Conversation:
            return _ConversationQuery(self._conversation)
        if model is share_api.Message:
            return _MessageQuery(self._messages)
        raise AssertionError(f"Unexpected model queried: {model}")

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def test_create_share_link_uses_conversation_message_snapshot(monkeypatch) -> None:
    conversation = SimpleNamespace(id="conv_1", user_id="user_1")
    user = SimpleNamespace(id="user_1")
    ordered_messages = [
        SimpleNamespace(id="e_parent", created_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        SimpleNamespace(id="e_child", created_at=datetime(2025, 1, 2, tzinfo=timezone.utc)),
    ]
    db = _DBStub(conversation, ordered_messages)

    monkeypatch.setattr(
        share_api.settings.__class__,
        "resolve_frontend_url",
        lambda _self, _origin=None: "http://frontend.test",
    )

    request = SimpleNamespace(headers={"origin": "http://frontend.test"})
    response = share_api.create_share_link("conv_1", request=request, current_user=user, db=db)

    assert response.share_url.startswith("http://frontend.test/share/")
    assert db.added, "Expected ConversationShare to be persisted"
    persisted_share = db.added[0]
    assert persisted_share.event_snapshot["message_ids"] == ["e_parent", "e_child"]
