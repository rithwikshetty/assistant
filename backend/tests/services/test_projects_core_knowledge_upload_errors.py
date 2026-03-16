from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api import projects_core_knowledge


class _DB:
    pass


def _build_client(monkeypatch: pytest.MonkeyPatch, upload_side_effect):  # type: ignore[no-untyped-def]
    router = APIRouter(prefix="/projects")
    projects_core_knowledge.register_knowledge_base_routes(
        router,
        get_project_for_member=lambda *_args, **_kwargs: SimpleNamespace(
            id="project-1",
            current_user_role="owner",
        ),
        serialize_project_knowledge_file=lambda file_record: file_record,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[projects_core_knowledge.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[projects_core_knowledge.get_db] = lambda: _DB()

    async def _raise(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise upload_side_effect

    monkeypatch.setattr(
        projects_core_knowledge.file_processing_service,
        "upload_file_for_background_processing",
        _raise,
    )
    return TestClient(app, raise_server_exceptions=False)


def test_knowledge_upload_preserves_http_exception_status(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(
        monkeypatch,
        HTTPException(status_code=413, detail="File too large"),
    )

    response = client.post(
        "/projects/00000000-0000-0000-0000-000000000001/knowledge-base/upload",
        files={"file": ("big.pdf", b"content", "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "File too large"


def test_knowledge_upload_masks_unexpected_error_details(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(
        monkeypatch,
        RuntimeError("storage key leaked"),
    )

    response = client.post(
        "/projects/00000000-0000-0000-0000-000000000001/knowledge-base/upload",
        files={"file": ("doc.pdf", b"content", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Failed to upload knowledge file"
