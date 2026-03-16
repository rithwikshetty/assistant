from types import SimpleNamespace

from app.database.models import File, StagedFile
from app.services.files.file_service import FileService


class _AllQueryStub:
    def __init__(self, rows):  # type: ignore[no-untyped-def]
        self._rows = list(rows)

    def options(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _DeleteQueryStub:
    def __init__(self):
        self.delete_called = False

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def delete(self, synchronize_session=False):  # type: ignore[no-untyped-def]
        del synchronize_session
        self.delete_called = True
        return 1


class _DBStub:
    def __init__(self, staged_rows):
        self._staged_rows = list(staged_rows)
        self._staged_query_count = 0
        self.staged_delete_query = _DeleteQueryStub()

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is StagedFile:
            self._staged_query_count += 1
            if self._staged_query_count == 1:
                return _AllQueryStub(self._staged_rows)
            if self._staged_query_count == 2:
                return _AllQueryStub([])
            return self.staged_delete_query
        if model is File:
            return _AllQueryStub([])
        raise AssertionError(f"Unexpected model query: {model}")


def test_promote_staged_files_uses_staged_blob_key_for_new_scope() -> None:
    service = FileService()
    staged = SimpleNamespace(
        id="staged-1",
        user_id="user-1",
        content_hash="hash-1",
        blob_object_id="blob-1",
        filename="user-1/staged-key.pdf",
        original_filename="proposal.pdf",
        file_type="pdf",
        file_size=123,
        extracted_text="parsed",
        processing_status="completed",
    )
    db = _DBStub([staged])
    create_calls = []

    def _create_file_record(**kwargs):  # type: ignore[no-untyped-def]
        create_calls.append(kwargs)
        return SimpleNamespace(id="file-1", content_hash=kwargs["content_hash"])

    service.create_file_record = _create_file_record  # type: ignore[assignment]

    promoted = service.promote_staged_files_to_conversation(
        staged_ids=["staged-1"],
        user_id="user-1",
        conversation_id="conversation-b",
        db=db,  # type: ignore[arg-type]
    )

    assert len(promoted) == 1
    assert create_calls
    assert create_calls[0]["blob_object_id"] == "blob-1"
    assert db.staged_delete_query.delete_called is True
