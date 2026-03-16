from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from app.database.models import ProjectArchiveJob, ProjectArchiveOutbox
from app.services.files import project_archive_service


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
    def __init__(self, outbox_rows, jobs):
        self.outbox_rows = list(outbox_rows)
        self.jobs = list(jobs)
        self.flush_calls = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is ProjectArchiveOutbox:
            return _QueryStub(self.outbox_rows)
        if model is ProjectArchiveJob:
            return _QueryStub(self.jobs)
        raise AssertionError(f"Unexpected model query: {model}")

    def flush(self):  # type: ignore[no-untyped-def]
        self.flush_calls += 1


def test_process_project_archive_outbox_batch_marks_completed(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        id=1,
        event_version=project_archive_service.PROJECT_ARCHIVE_EVENT_VERSION,
        archive_job_id="job-1",
        project_id="project-1",
        payload_jsonb={},
        retry_count=0,
        processed_at=None,
        error=None,
    )
    archive_job = SimpleNamespace(
        id="job-1",
        project_id="project-1",
        requested_by="user-1",
        status="pending",
        total_files=0,
        included_files=0,
        skipped_files=0,
        archive_filename=None,
        storage_key=None,
        blob_url=None,
        error=None,
        completed_at=None,
        expires_at=None,
    )
    db = _DBStub([outbox_row], [archive_job])

    monkeypatch.setattr(
        project_archive_service.file_service,
        "build_project_files_archive",
        lambda *_args, **_kwargs: {
            "archive_file": BytesIO(b"zip-bytes"),
            "total": 3,
            "included": 3,
            "skipped": 0,
            "archive_name": "project-knowledge.zip",
        },
    )
    monkeypatch.setattr(
        project_archive_service.blob_storage_service,
        "upload_fileobj_sync",
        lambda filename, _file_obj: f"https://blob.example/{filename}",
    )

    result = project_archive_service.process_project_archive_outbox_batch_sync(db, batch_size=10)

    assert result == {"scanned": 1, "processed": 1, "errors": 0}
    assert archive_job.status == "completed"
    assert archive_job.total_files == 3
    assert archive_job.included_files == 3
    assert archive_job.skipped_files == 0
    assert archive_job.archive_filename == "project-knowledge.zip"
    assert archive_job.storage_key is not None
    assert "project-1/job-1" in archive_job.storage_key
    assert outbox_row.processed_at is not None


def test_process_project_archive_outbox_batch_dead_letters_non_retryable_failure(monkeypatch) -> None:
    outbox_row = SimpleNamespace(
        id=1,
        event_version=project_archive_service.PROJECT_ARCHIVE_EVENT_VERSION,
        archive_job_id="job-1",
        project_id="project-1",
        payload_jsonb={},
        retry_count=0,
        processed_at=None,
        error=None,
    )
    archive_job = SimpleNamespace(
        id="job-1",
        project_id="project-1",
        requested_by="user-1",
        status="pending",
        total_files=0,
        included_files=0,
        skipped_files=0,
        archive_filename=None,
        storage_key=None,
        blob_url=None,
        error=None,
        completed_at=None,
        expires_at=None,
    )
    db = _DBStub([outbox_row], [archive_job])

    def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise ValueError("No project knowledge files found")

    monkeypatch.setattr(project_archive_service.file_service, "build_project_files_archive", _raise)

    result = project_archive_service.process_project_archive_outbox_batch_sync(db, batch_size=10)

    assert result == {"scanned": 1, "processed": 0, "errors": 1}
    assert archive_job.status == "failed"
    assert archive_job.error == "No project knowledge files found"
    assert outbox_row.processed_at is not None
    assert "dead_lettered:non_retryable_error" in str(outbox_row.error)
