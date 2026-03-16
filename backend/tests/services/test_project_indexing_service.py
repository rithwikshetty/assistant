from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.files import project_indexing_service as svc


class _OutboxQueryStub:
    def __init__(self, rows):
        self._rows = rows
        self.for_update_calls = []

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def with_for_update(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self.for_update_calls.append({"args": args, "kwargs": kwargs})
        return self

    def limit(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _FileQueryStub:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)

    def first(self):  # type: ignore[no-untyped-def]
        return self._rows[0] if self._rows else None


class _ChunkDeleteQueryStub:
    def __init__(self, db):
        self._db = db

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def delete(self, synchronize_session=False):  # type: ignore[no-untyped-def]
        del synchronize_session
        self._db.delete_calls += 1
        return 0


class _DBStub:
    def __init__(self, *, outbox_rows, file_row):
        self._outbox_rows = outbox_rows
        self._file_rows = [file_row] if file_row is not None else []
        self.outbox_query = None
        self.delete_calls = 0
        self.added = []
        self.flush_count = 0

    class _NestedTransaction:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

    def begin_nested(self):  # type: ignore[no-untyped-def]
        return self._NestedTransaction()

    def query(self, model):  # type: ignore[no-untyped-def]
        model_name = getattr(model, "__name__", "")
        if model_name == "ProjectFileIndexOutbox":
            self.outbox_query = _OutboxQueryStub(self._outbox_rows)
            return self.outbox_query
        if model_name == "File":
            return _FileQueryStub(self._file_rows)
        if model_name == "ProjectFileChunk":
            return _ChunkDeleteQueryStub(self)
        raise AssertionError(f"Unexpected query model: {model_name}")

    def add(self, item):  # type: ignore[no-untyped-def]
        self.added.append(item)

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_count += 1


def _build_file_row() -> SimpleNamespace:
    return SimpleNamespace(
        id="file-1",
        project_id="project-1",
        parent_file_id=None,
        processing_status="pending",
        processing_error=None,
        indexed_chunk_count=0,
        indexed_at=None,
        extracted_text="old text",
    )


def _build_outbox_row(*, retry_count=0, event_version=svc.PROJECT_FILE_INDEX_EVENT_VERSION) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        event_type=svc.PROJECT_FILE_INDEX_EVENT_TYPE,
        event_version=event_version,
        file_id="file-1",
        project_id="project-1",
        payload_jsonb={},
        created_at=datetime.now(timezone.utc),
        processed_at=None,
        retry_count=retry_count,
        error=None,
    )


def test_build_project_chunks_respects_overlap(monkeypatch) -> None:
    monkeypatch.setattr(svc.settings, "project_file_chunk_size_chars", 500)
    monkeypatch.setattr(svc.settings, "project_file_chunk_overlap_chars", 100)

    chunks = svc.build_project_chunks("a" * 1100)

    assert [item["chunk_index"] for item in chunks] == [0, 1, 2]
    assert [(item["char_start"], item["char_end"]) for item in chunks] == [
        (0, 500),
        (400, 900),
        (800, 1100),
    ]


def test_normalize_extracted_text_rejects_failed_parse_marker() -> None:
    try:
        svc._normalize_extracted_text("Failed to extract text from PDF file: timeout")
    except RuntimeError as exc:
        assert "Failed to extract text from PDF file" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_normalize_extracted_text_rejects_visual_only_marker() -> None:
    try:
        svc._normalize_extracted_text("[Image file: visual content cannot be extracted as text]")
    except ValueError as exc:
        assert "No extractable text content found for indexing" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_extract_project_text_uses_generic_file_processor_router(monkeypatch) -> None:
    file_row = SimpleNamespace(
        id="file-1",
        project_id="project-1",
        filename="blob-key",
        file_type="xlsx",
        original_filename="schedule.xlsx",
    )

    called = {"extract_text": False}

    monkeypatch.setattr(svc.blob_storage_service, "get_bytes", lambda _filename: b"sheet-bytes")

    async def _fake_extract_text(file_content, file_type, filename):  # type: ignore[no-untyped-def]
        called["extract_text"] = True
        assert file_content == b"sheet-bytes"
        assert file_type == "xlsx"
        assert filename == "schedule.xlsx"
        return "sheet summary"

    async def _fake_extract_text_with_llamaparse(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("extract_text_with_llamaparse should not be called directly")

    monkeypatch.setattr(svc.FileProcessor, "extract_text", _fake_extract_text)
    monkeypatch.setattr(svc.FileProcessor, "extract_text_with_llamaparse", _fake_extract_text_with_llamaparse)

    result = svc._extract_project_text(file_row)  # type: ignore[arg-type]

    assert result == "sheet summary"
    assert called["extract_text"] is True


def test_process_project_file_index_outbox_batch_sync_processes_rows(monkeypatch) -> None:
    outbox_row = _build_outbox_row()
    file_row = _build_file_row()
    db = _DBStub(outbox_rows=[outbox_row], file_row=file_row)

    monkeypatch.setattr(svc, "_extract_project_text", lambda file_row, **kwargs: "abcdefghij")
    monkeypatch.setattr(
        svc,
        "build_project_chunks",
        lambda text: [
            {
                "chunk_index": 0,
                "char_start": 0,
                "char_end": 5,
                "token_count": 2,
                "chunk_text": "abcde",
            },
            {
                "chunk_index": 1,
                "char_start": 5,
                "char_end": 10,
                "token_count": 2,
                "chunk_text": "fghij",
            },
        ],
    )
    monkeypatch.setattr(
        svc,
        "embed_chunk_texts",
        lambda texts, **_kwargs: [[0.1] * 1536 for _ in texts],
    )

    result = svc.process_project_file_index_outbox_batch_sync(
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 1, "errors": 0}
    assert outbox_row.processed_at is not None
    assert outbox_row.error is None
    assert file_row.processing_status == "completed"
    assert file_row.indexed_chunk_count == 2
    assert file_row.extracted_text is None
    assert db.delete_calls == 1
    assert len(db.added) == 2
    assert db.flush_count == 1
    assert db.outbox_query is not None
    assert db.outbox_query.for_update_calls == [{"args": (), "kwargs": {"skip_locked": True}}]


def test_process_project_file_index_outbox_batch_sync_retries_on_failure(monkeypatch) -> None:
    outbox_row = _build_outbox_row(retry_count=0)
    file_row = _build_file_row()
    db = _DBStub(outbox_rows=[outbox_row], file_row=file_row)

    monkeypatch.setattr(svc.settings, "project_file_index_outbox_max_retries", 3)
    monkeypatch.setattr(svc, "_extract_project_text", lambda file_row, **kwargs: (_ for _ in ()).throw(ValueError("boom")))

    result = svc.process_project_file_index_outbox_batch_sync(
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.retry_count == 1
    assert outbox_row.processed_at is None
    assert isinstance(outbox_row.error, str) and "boom" in outbox_row.error
    assert file_row.processing_status == "pending"
    assert isinstance(file_row.processing_error, str) and "boom" in file_row.processing_error


def test_process_project_file_index_outbox_batch_sync_dead_letters_non_retryable_errors(monkeypatch) -> None:
    outbox_row = _build_outbox_row(retry_count=0)
    file_row = _build_file_row()
    db = _DBStub(outbox_rows=[outbox_row], file_row=file_row)

    monkeypatch.setattr(svc.settings, "project_file_index_outbox_max_retries", 25)
    monkeypatch.setattr(
        svc,
        "_extract_project_text",
        lambda file_row, **kwargs: (_ for _ in ()).throw(ValueError("Failed to load file bytes from blob storage")),
    )

    result = svc.process_project_file_index_outbox_batch_sync(
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.retry_count == 1
    assert outbox_row.processed_at is not None
    assert isinstance(outbox_row.error, str) and outbox_row.error.startswith("dead_lettered:non_retryable_error")
    assert file_row.processing_status == "failed"
    assert isinstance(file_row.processing_error, str) and "Failed to load file bytes" in file_row.processing_error


def test_process_project_file_index_outbox_batch_sync_dead_letters_exhausted_rows(monkeypatch) -> None:
    outbox_row = _build_outbox_row(retry_count=2)
    file_row = _build_file_row()
    db = _DBStub(outbox_rows=[outbox_row], file_row=file_row)

    monkeypatch.setattr(svc.settings, "project_file_index_outbox_max_retries", 2)

    result = svc.process_project_file_index_outbox_batch_sync(
        db,  # type: ignore[arg-type]
        batch_size=10,
    )

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert outbox_row.processed_at is not None
    assert isinstance(outbox_row.error, str) and outbox_row.error.startswith("dead_lettered:max_retries_exceeded")
    assert file_row.processing_status == "failed"
