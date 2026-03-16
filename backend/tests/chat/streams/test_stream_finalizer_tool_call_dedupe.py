from types import SimpleNamespace

from app.chat.services.stream_finalizer import StreamFinalizer
from app.database.models import ToolCall


class _QueryStub:
    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def delete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return 0


class _DBStub:
    def __init__(self) -> None:
        self.added = []
        self.flush_count = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        assert model is ToolCall
        return _QueryStub()

    def add(self, obj):  # type: ignore[no-untyped-def]
        self.added.append(obj)

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_count += 1


def test_persist_tool_calls_dedupes_duplicate_tool_call_ids() -> None:
    finalizer = StreamFinalizer()
    db = _DBStub()

    finalizer._persist_tool_calls(
        db=db,  # type: ignore[arg-type]
        message=SimpleNamespace(id="assistant_msg_1"),
        run_id="run_1",
        tool_markers=[
            {
                "name": "load_skill",
                "call_id": "call_dup",
                "arguments": {"skill_id": "one"},
                "result": {"status": "completed"},
            },
            {
                "name": "request_user_input",
                "call_id": "call_dup",
                "result": {
                    "status": "completed",
                    "answers": [{"question_id": "scope", "option_label": "Detailed"}],
                },
            },
            {
                "name": "retrieval_web_search",
                "call_id": "call_unique",
                "result": {"status": "completed"},
            },
        ],
    )

    assert db.flush_count == 1
    inserted = [row for row in db.added if isinstance(row, ToolCall)]
    assert len(inserted) == 2
    inserted_call_ids = {row.tool_call_id for row in inserted}
    assert inserted_call_ids == {"call_dup", "call_unique"}
    deduped_row = next(row for row in inserted if row.tool_call_id == "call_dup")
    assert deduped_row.tool_name == "request_user_input"
