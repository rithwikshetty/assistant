from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.api import share as share_api


class _QueryStub:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):
        return self._result

    def all(self):
        if self._result is None:
            return []
        if isinstance(self._result, list):
            return self._result
        return [self._result]

    def order_by(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return self


class _DBStub:
    def __init__(self, share_obj, original_conversation, existing_import):
        self.share_obj = share_obj
        self.original_conversation = original_conversation
        self.existing_import = existing_import
        self.add_calls = 0
        self._conversation_query_count = 0

    def query(self, model, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        name = getattr(model, "__name__", str(model))
        if name == "ConversationShare":
            return _QueryStub(self.share_obj)
        if name == "Conversation":
            self._conversation_query_count += 1
            if self._conversation_query_count == 1:
                return _QueryStub(self.original_conversation)
            return _QueryStub(self.existing_import)
        return _QueryStub(None)

    def add(self, _obj):
        self.add_calls += 1

    def flush(self):
        return None

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def test_import_shared_conversation_returns_existing_import_without_cloning() -> None:
    user = SimpleNamespace(id="u_1")
    share = SimpleNamespace(
        conversation_id="conv_src",
        share_token="token_1",
        id="share_1",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        event_snapshot={"message_ids": []},
    )
    original = SimpleNamespace(id="conv_src", user_id="src_user", title="Original", conversation_metadata={})
    existing = SimpleNamespace(id="conv_existing", title="Shared - Original")

    db = _DBStub(share, original, existing)

    response = share_api.import_shared_conversation("token_1", current_user=user, db=db)

    assert response.conversation_id == "conv_existing"
    assert "already imported" in response.message.lower()
    assert db.add_calls == 0
