from types import SimpleNamespace

from app.chat.services.stream_finalizer import StreamFinalizer
from app.database.models import PendingUserInput


class _QueryStub:
    def __init__(self):
        self.first_result = None
        self.update_payload = None

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):  # type: ignore[no-untyped-def]
        return self.first_result

    def update(self, values, synchronize_session=False):  # type: ignore[no-untyped-def]
        del synchronize_session
        self.update_payload = values
        return 0


class _DBStub:
    def __init__(self):
        self.pending_query = _QueryStub()
        self.added = []
        self.flush_count = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        assert model is PendingUserInput
        return self.pending_query

    def add(self, obj):  # type: ignore[no-untyped-def]
        self.added.append(obj)

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_count += 1


def test_persist_pending_user_inputs_creates_pending_row_for_request_user_input() -> None:
    finalizer = StreamFinalizer()
    db = _DBStub()

    finalizer._persist_pending_user_inputs(
        db=db,  # type: ignore[arg-type]
        message=SimpleNamespace(id="assistant_msg_1"),
        run_id="run_1",
        run_status="paused",
        tool_markers=[
            {
                "name": "request_user_input",
                "call_id": "call_1",
                "result": {
                    "status": "pending",
                    "request": {
                        "tool": "request_user_input",
                        "title": "Choose",
                        "prompt": "Pick one",
                    },
                },
            }
        ],
    )

    assert db.flush_count == 1
    assert len(db.added) == 1

    row = db.added[0]
    assert row.run_id == "run_1"
    assert row.message_id == "assistant_msg_1"
    assert row.tool_call_id == "call_1"
    assert row.status == "pending"
    assert row.request_jsonb == {
        "tool_name": "request_user_input",
        "request": {
            "tool": "request_user_input",
            "title": "Choose",
            "prompt": "Pick one",
        },
        "result": {
            "status": "pending",
            "request": {
                "tool": "request_user_input",
                "title": "Choose",
                "prompt": "Pick one",
            },
            "interaction_type": "user_input",
        },
    }


def test_persist_pending_user_inputs_canonicalizes_request_user_input_payload() -> None:
    finalizer = StreamFinalizer()
    db = _DBStub()

    finalizer._persist_pending_user_inputs(
        db=db,  # type: ignore[arg-type]
        message=SimpleNamespace(id="assistant_msg_2"),
        run_id="run_2",
        run_status="paused",
        tool_markers=[
            {
                "name": "request_user_input",
                "call_id": "call_input_2",
                "result": {
                    "status": "pending",
                    "interaction_type": "user_input",
                    "request": {
                        "title": "Need direction",
                        "prompt": "Choose the next step",
                    },
                },
            }
        ],
    )

    assert db.flush_count == 1
    assert len(db.added) == 1
    row = db.added[0]
    assert row.run_id == "run_2"
    assert row.message_id == "assistant_msg_2"
    assert row.tool_call_id == "call_input_2"
    assert row.status == "pending"
    assert row.request_jsonb == {
        "tool_name": "request_user_input",
        "request": {
            "tool": "request_user_input",
            "title": "Need direction",
            "prompt": "Choose the next step",
        },
        "result": {
            "status": "pending",
            "interaction_type": "user_input",
            "request": {
                "title": "Need direction",
                "prompt": "Choose the next step",
            },
        },
    }
