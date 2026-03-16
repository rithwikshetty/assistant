from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import staged_files


class _DB:
    pass


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(staged_files.router)
    app.dependency_overrides[staged_files.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[staged_files.get_db] = lambda: _DB()
    return TestClient(app, raise_server_exceptions=False)


def test_staged_upload_returns_async_processing_state(monkeypatch) -> None:
    client = _build_client()

    async def _upload(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            id="staged-1",
            filename="uploads/staged-1.pdf",
            original_filename="proposal.pdf",
            file_type="pdf",
            file_size=42,
            created_at="2026-03-11T00:00:00Z",
            processing_status="pending",
            processing_error=None,
            redaction_requested=False,
            redaction_applied=False,
            redacted_categories_jsonb=[],
            extracted_text=None,
        )

    monkeypatch.setattr(staged_files.file_processing_service, "upload_and_process_staged_file", _upload)

    response = client.post("/staged-files/upload", files={"file": ("proposal.pdf", b"hello", "application/pdf")})

    assert response.status_code == 200
    assert response.json()["processing_status"] == "pending"
    assert response.json()["extracted_text"] is None


def test_get_staged_file_returns_processing_state(monkeypatch) -> None:
    client = _build_client()

    monkeypatch.setattr(
        staged_files.file_service,
        "get_staged_by_id",
        lambda *_args, **_kwargs: SimpleNamespace(
            id="staged-1",
            filename="uploads/staged-1.pdf",
            original_filename="proposal.pdf",
            file_type="pdf",
            file_size=42,
            created_at="2026-03-11T00:00:00Z",
            processing_status="completed",
            processing_error=None,
            redaction_requested=False,
            redaction_applied=False,
            redacted_categories_jsonb=[],
            extracted_text="Extracted text",
        ),
    )

    response = client.get("/staged-files/staged-1")

    assert response.status_code == 200
    assert response.json()["processing_status"] == "completed"
    assert response.json()["extracted_text"] == "Extracted text"
