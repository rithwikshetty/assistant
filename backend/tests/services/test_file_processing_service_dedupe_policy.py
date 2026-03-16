import asyncio
import importlib
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.services.files.file_processing_service import FileProcessingService

fps = importlib.import_module("app.services.files.file_processing_service")


class _DBStub:
    def __init__(self):
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_count += 1

    def commit(self):  # type: ignore[no-untyped-def]
        self.commit_count += 1

    def rollback(self):  # type: ignore[no-untyped-def]
        self.rollback_count += 1

    def refresh(self, _obj):  # type: ignore[no-untyped-def]
        return None


class _UploadStub:
    def __init__(self, *, filename: str, content: bytes):
        self.filename = filename
        self._content = content
        self.file = None

    async def read(self):  # type: ignore[no-untyped-def]
        return self._content

    async def seek(self, _offset):  # type: ignore[no-untyped-def]
        return None


def test_upload_and_process_file_cross_scope_duplicate_uses_new_blob(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()
        upload_calls = []
        create_calls = []

        existing_file = SimpleNamespace(
            id="existing-1",
            conversation_id="conversation-a",
            project_id=None,
            user_id="user-1",
            original_filename="legacy.pdf",
            filename="user-1/legacy-key.pdf",
            blob_url="blob://legacy",
        )

        async def _fake_process_file(_file, **_kwargs):  # type: ignore[no-untyped-def]
            return {
                "file_content": b"new-bytes",
                "file_type": "pdf",
                "file_size": 9,
                "extracted_text": "parsed",
                "original_filename": "proposal.pdf",
                "redaction_performed": False,
            }

        async def _fake_upload(filename, content):  # type: ignore[no-untyped-def]
            upload_calls.append((filename, content))
            return "blob://new"

        def _fake_create_file_record(**kwargs):  # type: ignore[no-untyped-def]
            create_calls.append(kwargs)
            return SimpleNamespace(
                id="new-1",
                filename=kwargs["storage_key"],
                blob_url=kwargs["blob_url"],
                original_filename=kwargs["original_filename"],
            )

        monkeypatch.setattr(fps.FileProcessor, "process_file", _fake_process_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **_kwargs: existing_file)
        monkeypatch.setattr(fps.file_service, "generate_filename", lambda _name, _uid: "user-1/new-key.pdf")
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fake_upload)
        monkeypatch.setattr(fps.file_service, "create_file_record", _fake_create_file_record)
        monkeypatch.setattr(
            fps.file_service,
            "get_file_by_id",
            lambda file_id, user_id, sync_db, **_kwargs: SimpleNamespace(
                id=file_id,
                filename="user-1/new-key.pdf",
                blob_url="blob://new",
                original_filename="proposal.pdf",
            ) if file_id == "new-1" and user_id == "user-1" else None,
        )

        file_row, processed = await service.upload_and_process_file(
            file=SimpleNamespace(filename="proposal.pdf"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            conversation_id="conversation-b",
        )

        assert processed["file_type"] == "pdf"
        assert file_row.filename == "user-1/new-key.pdf"
        assert file_row.blob_url == "blob://new"
        assert upload_calls == [("user-1/new-key.pdf", b"new-bytes")]
        assert create_calls and create_calls[0]["storage_key"] == "user-1/new-key.pdf"
        assert create_calls[0]["blob_url"] == "blob://new"
        assert db.commit_count == 1
        assert db.flush_count == 1

    asyncio.run(_run())


def test_upload_and_process_file_same_scope_duplicate_reuses_existing(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()

        existing_file = SimpleNamespace(
            id="existing-1",
            conversation_id="conversation-a",
            project_id=None,
            user_id="user-1",
            original_filename="current.pdf",
            filename="user-1/current-key.pdf",
            blob_url="blob://existing",
        )

        async def _fake_process_file(_file, **_kwargs):  # type: ignore[no-untyped-def]
            return {
                "file_content": b"same-bytes",
                "file_type": "pdf",
                "file_size": 10,
                "extracted_text": "parsed",
                "original_filename": "current.pdf",
                "redaction_performed": False,
            }

        async def _fail_upload(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("upload should not run for same-scope duplicate")

        monkeypatch.setattr(fps.FileProcessor, "process_file", _fake_process_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **_kwargs: existing_file)
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fail_upload)

        file_row, processed = await service.upload_and_process_file(
            file=SimpleNamespace(filename="current.pdf"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            conversation_id="conversation-a",
        )

        assert processed["file_type"] == "pdf"
        assert file_row is existing_file
        assert db.commit_count == 0
        assert db.flush_count == 0

    asyncio.run(_run())


def test_upload_and_process_file_cleans_blob_when_create_record_integrity_error(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()

        recovered = SimpleNamespace(id="existing-2")
        deleted = []

        async def _fake_process_file(_file, **_kwargs):  # type: ignore[no-untyped-def]
            return {
                "file_content": b"new-bytes",
                "file_type": "pdf",
                "file_size": 9,
                "extracted_text": "parsed",
                "original_filename": "proposal.pdf",
                "redaction_performed": False,
            }

        async def _fake_upload(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://new"

        def _raise_integrity_error(**_kwargs):  # type: ignore[no-untyped-def]
            raise IntegrityError("insert", {}, Exception("duplicate"))

        monkeypatch.setattr(fps.FileProcessor, "process_file", _fake_process_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **_kwargs: None)
        monkeypatch.setattr(fps.file_service, "generate_filename", lambda _name, _uid: "user-1/new-key.pdf")
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fake_upload)
        monkeypatch.setattr(fps.file_service, "create_file_record", _raise_integrity_error)
        monkeypatch.setattr(fps.file_service, "get_scope_file_by_hash", lambda **_kwargs: recovered)
        monkeypatch.setattr(fps.blob_storage_service, "blob_client", object())
        monkeypatch.setattr(
            fps.blob_storage_service,
            "delete",
            lambda filename: (deleted.append(filename), True)[1],
        )

        file_row, processed = await service.upload_and_process_file(
            file=SimpleNamespace(filename="proposal.pdf"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            conversation_id="conversation-b",
        )

        assert processed["file_type"] == "pdf"
        assert file_row is recovered
        assert deleted == ["user-1/new-key.pdf"]
        assert db.rollback_count == 1

    asyncio.run(_run())


def test_upload_and_process_file_rehydrates_created_row_before_return(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()

        created_row = SimpleNamespace(id="new-1")
        hydrated_row = SimpleNamespace(
            id="new-1",
            filename="user-1/new-key.pdf",
            blob_url="blob://new",
            extracted_text="parsed",
        )

        async def _fake_process_file(_file, **_kwargs):  # type: ignore[no-untyped-def]
            return {
                "file_content": b"new-bytes",
                "file_type": "pdf",
                "file_size": 9,
                "extracted_text": "parsed",
                "original_filename": "proposal.pdf",
                "redaction_performed": False,
            }

        async def _fake_upload(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://new"

        monkeypatch.setattr(fps.FileProcessor, "process_file", _fake_process_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **_kwargs: None)
        monkeypatch.setattr(fps.file_service, "generate_filename", lambda _name, _uid: "user-1/new-key.pdf")
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fake_upload)
        monkeypatch.setattr(fps.file_service, "create_file_record", lambda **_kwargs: created_row)
        monkeypatch.setattr(
            fps.file_service,
            "get_file_by_id",
            lambda file_id, user_id, sync_db, **_kwargs: hydrated_row
            if file_id == "new-1" and user_id == "user-1"
            else None,
        )

        file_row, processed = await service.upload_and_process_file(
            file=SimpleNamespace(filename="proposal.pdf"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            conversation_id="conversation-b",
        )

        assert processed["file_type"] == "pdf"
        assert file_row is hydrated_row
        assert db.commit_count == 1

    asyncio.run(_run())


def test_upload_file_for_background_processing_cleans_blob_when_create_record_integrity_error(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()
        recovered = SimpleNamespace(id="existing-project-file")
        deleted = []

        async def _validate_file(_file):  # type: ignore[no-untyped-def]
            return "pdf"

        async def _fake_upload(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://new"

        def _raise_integrity_error(**_kwargs):  # type: ignore[no-untyped-def]
            raise IntegrityError("insert", {}, Exception("duplicate"))

        monkeypatch.setattr(fps.FileProcessor, "validate_file", _validate_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **_kwargs: None)
        monkeypatch.setattr(fps.file_service, "generate_filename", lambda _name, _uid: "user-1/new-key.pdf")
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fake_upload)
        monkeypatch.setattr(fps.file_service, "create_file_record", _raise_integrity_error)
        monkeypatch.setattr(fps.file_service, "get_scope_file_by_hash", lambda **_kwargs: recovered)
        monkeypatch.setattr(fps.blob_storage_service, "blob_client", object())
        monkeypatch.setattr(
            fps.blob_storage_service,
            "delete",
            lambda filename: (deleted.append(filename), True)[1],
        )

        file_row = await service.upload_file_for_background_processing(
            file=_UploadStub(filename="proposal.pdf", content=b"abc"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            project_id="project-1",
            redact=False,
        )

        assert file_row is recovered
        assert deleted == ["user-1/new-key.pdf"]
        assert db.rollback_count == 1

    asyncio.run(_run())


def test_upload_file_for_background_processing_rehydrates_created_row_before_return(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()

        created_row = SimpleNamespace(
            id="project-file-1",
            indexed_chunk_count=0,
            indexed_at=None,
            processing_error=None,
            processing_status="pending",
        )
        hydrated_row = SimpleNamespace(
            id="project-file-1",
            filename="user-1/new-key.pdf",
            processing_status="pending",
            user_id="user-1",
        )

        async def _validate_file(_file):  # type: ignore[no-untyped-def]
            return "pdf"

        async def _fake_upload(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://new"

        monkeypatch.setattr(fps.FileProcessor, "validate_file", _validate_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_file", lambda **_kwargs: None)
        monkeypatch.setattr(fps.file_service, "generate_filename", lambda _name, _uid: "user-1/new-key.pdf")
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fake_upload)
        monkeypatch.setattr(fps.file_service, "create_file_record", lambda **_kwargs: created_row)
        monkeypatch.setattr(fps, "enqueue_project_file_index_outbox_event", lambda **_kwargs: None)
        monkeypatch.setattr(fps, "dispatch_project_file_index_outbox_worker", lambda: None)
        monkeypatch.setattr(
            fps.file_service,
            "get_file_by_id",
            lambda file_id, user_id, sync_db, **_kwargs: hydrated_row
            if file_id == "project-file-1" and user_id == "user-1"
            else None,
        )

        file_row = await service.upload_file_for_background_processing(
            file=_UploadStub(filename="proposal.pdf", content=b"abc"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            project_id="project-1",
            redact=False,
        )

        assert file_row is hydrated_row
        assert db.commit_count == 1

    asyncio.run(_run())


def test_upload_and_process_staged_file_cleans_blob_when_create_record_integrity_error(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()
        recovered = SimpleNamespace(id="staged-existing")
        deleted = []

        async def _validate_file(_file):  # type: ignore[no-untyped-def]
            return "pdf"

        async def _fake_upload(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://new"

        def _raise_integrity_error(**_kwargs):  # type: ignore[no-untyped-def]
            raise IntegrityError("insert", {}, Exception("duplicate"))

        duplicate_checks = {"count": 0}

        def _check_duplicate_staged(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            duplicate_checks["count"] += 1
            if duplicate_checks["count"] == 1:
                return None
            return recovered

        monkeypatch.setattr(fps.FileProcessor, "validate_file", _validate_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_staged", _check_duplicate_staged)
        monkeypatch.setattr(fps.file_service, "generate_filename", lambda _name, _uid: "user-1/new-key.pdf")
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fake_upload)
        monkeypatch.setattr(fps.file_service, "create_staged_file_record", _raise_integrity_error)
        monkeypatch.setattr(fps, "enqueue_staged_file_processing_outbox_event", lambda **_kwargs: None)
        monkeypatch.setattr(fps, "dispatch_staged_file_processing_outbox_worker", lambda: None)
        monkeypatch.setattr(fps.blob_storage_service, "blob_client", object())
        monkeypatch.setattr(
            fps.blob_storage_service,
            "delete",
            lambda filename: (deleted.append(filename), True)[1],
        )

        staged = await service.upload_and_process_staged_file(
            file=_UploadStub(filename="proposal.pdf", content=b"new-bytes"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            draft_id="draft-1",
            redact=False,
        )

        assert staged is recovered
        assert deleted == ["user-1/new-key.pdf"]
        assert db.rollback_count == 1

    asyncio.run(_run())


def test_upload_and_process_staged_file_rehydrates_created_row_before_return(monkeypatch) -> None:
    async def _run() -> None:
        service = FileProcessingService()
        db = _DBStub()

        created_row = SimpleNamespace(id="staged-new-1")
        hydrated_row = SimpleNamespace(
            id="staged-new-1",
            filename="user-1/new-key.pdf",
            processing_status="pending",
            extracted_text=None,
        )

        async def _validate_file(_file):  # type: ignore[no-untyped-def]
            return "pdf"

        async def _fake_upload(_filename, _content):  # type: ignore[no-untyped-def]
            return "blob://new"

        monkeypatch.setattr(fps.FileProcessor, "validate_file", _validate_file)
        monkeypatch.setattr(fps.file_service, "get_user_redaction_list", lambda _uid, _db: [])
        monkeypatch.setattr(fps.file_service, "calculate_content_hash", lambda _content, **_kwargs: "hash-1")
        monkeypatch.setattr(fps.file_service, "check_duplicate_staged", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(fps.file_service, "generate_filename", lambda _name, _uid: "user-1/new-key.pdf")
        monkeypatch.setattr(fps.blob_storage_service, "upload", _fake_upload)
        monkeypatch.setattr(fps.file_service, "create_staged_file_record", lambda **_kwargs: created_row)
        monkeypatch.setattr(fps, "enqueue_staged_file_processing_outbox_event", lambda **_kwargs: None)
        monkeypatch.setattr(fps, "dispatch_staged_file_processing_outbox_worker", lambda: None)
        monkeypatch.setattr(
            fps.file_service,
            "get_staged_by_id",
            lambda staged_id, user_id, sync_db: hydrated_row
            if staged_id == "staged-new-1" and user_id == "user-1"
            else None,
        )

        staged = await service.upload_and_process_staged_file(
            file=_UploadStub(filename="proposal.pdf", content=b"new-bytes"),  # type: ignore[arg-type]
            user_id="user-1",
            db=db,  # type: ignore[arg-type]
            draft_id="draft-1",
            redact=False,
        )

        assert staged is hydrated_row
        assert db.commit_count == 1

    asyncio.run(_run())
