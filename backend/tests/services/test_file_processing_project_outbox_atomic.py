import asyncio
import importlib
from types import SimpleNamespace

from app.services.files.file_processing_service import FileProcessingService

fps = importlib.import_module("app.services.files.file_processing_service")


class _UploadStub:
    def __init__(self, *, filename: str, content: bytes):
        self.filename = filename
        self._content = content

    async def read(self):  # type: ignore[no-untyped-def]
        return self._content

    async def seek(self, _offset):  # type: ignore[no-untyped-def]
        return None


class _DBStub:
    def __init__(self, order):
        self.order = order
        self.commit_count = 0

    def flush(self):  # type: ignore[no-untyped-def]
        self.order.append("flush")

    def commit(self):  # type: ignore[no-untyped-def]
        self.order.append("commit")
        self.commit_count += 1

    def refresh(self, _obj):  # type: ignore[no-untyped-def]
        self.order.append("refresh")

    def rollback(self):  # type: ignore[no-untyped-def]
        self.order.append("rollback")


def test_upload_file_for_background_processing_writes_outbox_before_commit(monkeypatch) -> None:
    async def _run() -> None:
        order: list[str] = []
        db = _DBStub(order)
        service = FileProcessingService()

        file_record = SimpleNamespace(
            id="file-1",
            processing_status="pending",
            indexed_chunk_count=0,
            indexed_at=None,
            processing_error=None,
        )

        async def _validate_file(_file):  # type: ignore[no-untyped-def]
            return "pdf"

        async def _upload_blob(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://url"

        monkeypatch.setattr(fps.FileProcessor, "validate_file", _validate_file)
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda content, **kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **kwargs: None)
        monkeypatch.setattr(
            fps.file_service,
            "generate_filename",
            lambda filename, user_id: f"{user_id}/generated.pdf",
        )
        monkeypatch.setattr(fps.blob_storage_service, "upload", _upload_blob)
        monkeypatch.setattr(fps.file_service, "create_file_record", lambda **kwargs: file_record)
        monkeypatch.setattr(fps, "enqueue_project_file_index_outbox_event", lambda **kwargs: order.append("enqueue_outbox"))
        monkeypatch.setattr(fps, "dispatch_project_file_index_outbox_worker", lambda: order.append("dispatch_worker"))

        upload = _UploadStub(filename="knowledge.pdf", content=b"test-content")
        result = await service.upload_file_for_background_processing(
            file=upload,  # type: ignore[arg-type]
            user_id="user-1",
            project_id="project-1",
            db=db,  # type: ignore[arg-type]
        )

        assert result is file_record
        assert db.commit_count == 1
        assert order.index("enqueue_outbox") < order.index("commit")
        assert order.index("commit") < order.index("dispatch_worker")

    asyncio.run(_run())


def test_upload_file_for_background_processing_propagates_redaction_payload(monkeypatch) -> None:
    async def _run() -> None:
        order: list[str] = []
        db = _DBStub(order)
        service = FileProcessingService()

        file_record = SimpleNamespace(
            id="file-1",
            processing_status="pending",
            indexed_chunk_count=0,
            indexed_at=None,
            processing_error=None,
        )

        captured = {
            "content_hash_redacted": None,
            "created_original_filename": None,
            "outbox_payload": None,
        }

        async def _validate_file(_file):  # type: ignore[no-untyped-def]
            return "pdf"

        async def _upload_blob(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://url"

        def _calc_hash(_content, **kwargs):  # type: ignore[no-untyped-def]
            captured["content_hash_redacted"] = kwargs.get("redacted")
            return "hash-1"

        def _create_file_record(**kwargs):  # type: ignore[no-untyped-def]
            captured["created_original_filename"] = kwargs.get("original_filename")
            return file_record

        def _enqueue(**kwargs):  # type: ignore[no-untyped-def]
            captured["outbox_payload"] = kwargs.get("payload")
            order.append("enqueue_outbox")

        monkeypatch.setattr(fps.FileProcessor, "validate_file", _validate_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: ["Alice"])
        monkeypatch.setattr(fps, "redact_filename", lambda filename, user_redaction_list: SimpleNamespace(text="redacted.pdf"))
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", _calc_hash)
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **kwargs: None)
        monkeypatch.setattr(
            fps.file_service,
            "generate_filename",
            lambda filename, user_id: f"{user_id}/generated.pdf",
        )
        monkeypatch.setattr(fps.blob_storage_service, "upload", _upload_blob)
        monkeypatch.setattr(fps.file_service, "create_file_record", _create_file_record)
        monkeypatch.setattr(fps, "enqueue_project_file_index_outbox_event", _enqueue)
        monkeypatch.setattr(fps, "dispatch_project_file_index_outbox_worker", lambda: order.append("dispatch_worker"))

        upload = _UploadStub(filename="knowledge.pdf", content=b"test-content")
        result = await service.upload_file_for_background_processing(
            file=upload,  # type: ignore[arg-type]
            user_id="user-1",
            project_id="project-1",
            db=db,  # type: ignore[arg-type]
            redact=True,
        )

        assert result is file_record
        assert captured["content_hash_redacted"] is True
        assert captured["created_original_filename"] == "redacted.pdf"
        assert captured["outbox_payload"] == {
            "uploaded_by": "user-1",
            "filename": "redacted.pdf",
            "redact": True,
            "user_redaction_list": ["Alice"],
        }

    asyncio.run(_run())


def test_upload_file_for_background_processing_redacts_spreadsheet_bytes_before_upload(monkeypatch) -> None:
    async def _run() -> None:
        order: list[str] = []
        db = _DBStub(order)
        service = FileProcessingService()

        file_record = SimpleNamespace(
            id="file-1",
            processing_status="pending",
            indexed_chunk_count=0,
            indexed_at=None,
            processing_error=None,
        )

        captured = {
            "uploaded_bytes": None,
            "hash_input": None,
        }

        async def _validate_file(_file):  # type: ignore[no-untyped-def]
            return "xlsx"

        async def _redact_spreadsheet_bytes(
            _content,  # type: ignore[no-untyped-def]
            _file_type,  # type: ignore[no-untyped-def]
            *,
            user_redaction_list,  # type: ignore[no-untyped-def]
        ):
            assert user_redaction_list == ["Alice"]
            return SimpleNamespace(
                file_content=b"redacted-bytes",
                redaction_performed=True,
                redaction_hits=["Alice"],
            )

        async def _upload_blob(_filename, content):  # type: ignore[no-untyped-def]
            captured["uploaded_bytes"] = content
            return "blob://url"

        def _calc_hash(content, **_kwargs):  # type: ignore[no-untyped-def]
            captured["hash_input"] = content
            return "hash-redacted"

        monkeypatch.setattr(fps.FileProcessor, "validate_file", _validate_file)
        monkeypatch.setattr(fps.FileProcessor, "is_spreadsheet_type", lambda file_type: file_type == "xlsx")
        monkeypatch.setattr(fps.FileProcessor, "supports_spreadsheet_byte_redaction", lambda file_type: file_type == "xlsx")
        monkeypatch.setattr(fps.FileProcessor, "redact_spreadsheet_file_content", _redact_spreadsheet_bytes)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: ["Alice"])
        monkeypatch.setattr(
            fps,
            "redact_filename",
            lambda filename, user_redaction_list: SimpleNamespace(text="redacted-sheet.xlsx"),
        )
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", _calc_hash)
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **kwargs: None)
        monkeypatch.setattr(
            fps.file_service,
            "generate_filename",
            lambda filename, user_id: f"{user_id}/generated.xlsx",
        )
        monkeypatch.setattr(fps.blob_storage_service, "upload", _upload_blob)
        monkeypatch.setattr(fps.file_service, "create_file_record", lambda **kwargs: file_record)
        monkeypatch.setattr(fps, "enqueue_project_file_index_outbox_event", lambda **kwargs: order.append("enqueue_outbox"))
        monkeypatch.setattr(fps, "dispatch_project_file_index_outbox_worker", lambda: order.append("dispatch_worker"))

        upload = _UploadStub(filename="raw.xlsx", content=b"raw-bytes")
        result = await service.upload_file_for_background_processing(
            file=upload,  # type: ignore[arg-type]
            user_id="user-1",
            project_id="project-1",
            db=db,  # type: ignore[arg-type]
            redact=True,
        )

        assert result is file_record
        assert captured["hash_input"] == b"redacted-bytes"
        assert captured["uploaded_bytes"] == b"redacted-bytes"

    asyncio.run(_run())
