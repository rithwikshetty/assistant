from __future__ import annotations

from types import SimpleNamespace

from app.database.models import StagedFile, StagedFileProcessingOutbox
from app.services.files import staged_processing_service


class _QueryStub:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def with_for_update(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def limit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _DBStub:
    def __init__(self, outbox_rows, staged_rows):
        self.outbox_rows = list(outbox_rows)
        self.staged_rows = list(staged_rows)
        self.flush_calls = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is StagedFileProcessingOutbox:
            return _QueryStub(self.outbox_rows)
        if model is StagedFile:
            return _QueryStub(self.staged_rows)
        raise AssertionError(f"Unexpected model query: {model}")

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_calls += 1


def test_process_staged_file_processing_outbox_batch_marks_completed(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        id=1,
        event_version=staged_processing_service.STAGED_FILE_PROCESS_EVENT_VERSION,
        staged_file_id="staged-1",
        user_id="user-1",
        payload_jsonb={"redact": False},
        retry_count=0,
        processed_at=None,
        error=None,
    )
    staged_row = SimpleNamespace(
        id="staged-1",
        user_id="user-1",
        filename="uploads/staged-1.pdf",
        original_filename="proposal.pdf",
        file_type="pdf",
        processing_status="pending",
        processing_error=None,
        extracted_text=None,
        processed_at=None,
        redaction_applied=False,
        redacted_categories_jsonb=[],
    )
    db = _DBStub([outbox_row], [staged_row])

    monkeypatch.setattr(staged_processing_service.blob_storage_service, "get_bytes", lambda *_args, **_kwargs: b"hello")

    async def _extract_text(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return "Extracted text"

    monkeypatch.setattr(staged_processing_service.FileProcessor, "extract_text", _extract_text)

    result = staged_processing_service.process_staged_file_processing_outbox_batch_sync(db, batch_size=10)

    assert result == {"scanned": 1, "processed": 1, "errors": 0}
    assert staged_row.processing_status == "completed"
    assert staged_row.processing_error is None
    assert staged_row.extracted_text == "Extracted text"
    assert staged_row.processed_at is not None
    assert outbox_row.processed_at is not None
    assert outbox_row.error is None


def test_process_staged_file_processing_outbox_batch_dead_letters_non_retryable_failure(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        id=1,
        event_version=staged_processing_service.STAGED_FILE_PROCESS_EVENT_VERSION,
        staged_file_id="staged-1",
        user_id="user-1",
        payload_jsonb={},
        retry_count=0,
        processed_at=None,
        error=None,
    )
    staged_row = SimpleNamespace(
        id="staged-1",
        user_id="user-1",
        filename="uploads/staged-1.pdf",
        original_filename="proposal.pdf",
        file_type="pdf",
        processing_status="pending",
        processing_error=None,
        extracted_text=None,
        processed_at=None,
        redaction_applied=False,
        redacted_categories_jsonb=[],
    )
    db = _DBStub([outbox_row], [staged_row])

    monkeypatch.setattr(staged_processing_service.blob_storage_service, "get_bytes", lambda *_args, **_kwargs: None)

    result = staged_processing_service.process_staged_file_processing_outbox_batch_sync(db, batch_size=10)

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert staged_row.processing_status == "failed"
    assert staged_row.processing_error == "Failed to load file bytes from blob storage"
    assert outbox_row.processed_at is not None
    assert "dead_lettered:non_retryable_error" in str(outbox_row.error)
