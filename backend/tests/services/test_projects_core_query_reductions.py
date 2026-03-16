from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api import projects_core, projects_core_knowledge


class _DB:
    """Minimal DB stub for route tests."""


def test_get_project_uses_role_from_member_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    project = SimpleNamespace(id="project-1", current_user_role="owner")

    monkeypatch.setattr(projects_core, "_get_project_for_member", lambda *_args, **_kwargs: project)

    def _unexpected_rehydrate(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("should not re-query membership role")

    monkeypatch.setattr(projects_core, "_set_current_user_role", _unexpected_rehydrate)

    result = projects_core.get_project(
        project_id=uuid4(),
        user=SimpleNamespace(id="user-1"),
        db=_DB(),
    )

    assert result is project


def _build_knowledge_client(current_user_role: str) -> TestClient:
    router = APIRouter(prefix="/projects")
    projects_core_knowledge.register_knowledge_base_routes(
        router,
        get_project_for_member=lambda *_args, **_kwargs: SimpleNamespace(
            id="project-1",
            current_user_role=current_user_role,
        ),
        serialize_project_knowledge_file=lambda file_record: file_record,
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[projects_core_knowledge.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[projects_core_knowledge.get_db] = lambda: _DB()
    return TestClient(app, raise_server_exceptions=False)


def test_delete_knowledge_files_uses_prefetched_role(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_knowledge_client("owner")

    monkeypatch.setattr(
        projects_core_knowledge.file_service,
        "delete_project_files",
        lambda *_args, **_kwargs: 4,
    )

    response = client.delete("/projects/00000000-0000-0000-0000-000000000001/knowledge-base/files")

    assert response.status_code == 200
    assert response.json() == {"message": "4 file(s) deleted", "deleted": 4}


def test_delete_knowledge_files_requires_owner_role(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_knowledge_client("member")

    delete_called = False

    def _delete(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        nonlocal delete_called
        delete_called = True
        return 1

    monkeypatch.setattr(projects_core_knowledge.file_service, "delete_project_files", _delete)

    response = client.delete("/projects/00000000-0000-0000-0000-000000000001/knowledge-base/files")

    assert response.status_code == 403
    assert response.json()["detail"] == "Only a project owner can delete all knowledge base files"
    assert delete_called is False


def test_project_knowledge_context_uses_lightweight_summary_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_knowledge_client("owner")

    monkeypatch.setattr(
        projects_core_knowledge.file_service,
        "get_project_file_aggregate_stats",
        lambda *_args, **_kwargs: {
            "total_files": 2,
            "total_size": 30,
            "file_types": {"pdf": 2},
        },
    )
    monkeypatch.setattr(
        projects_core_knowledge.file_service,
        "list_project_knowledge_summary_items",
        lambda *_args, **_kwargs: [
            {
                "file_id": "file-1",
                "original_filename": "alpha.pdf",
                "file_type": "pdf",
                "file_size": 10,
                "created_at": "2026-03-11T00:00:00Z",
            },
            {
                "file_id": "file-2",
                "original_filename": "beta.pdf",
                "file_type": "pdf",
                "file_size": 20,
                "created_at": "2026-03-11T01:00:00Z",
            },
        ],
    )

    def _unexpected_stats(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("full project file stats should not be used for context summary")

    monkeypatch.setattr(projects_core_knowledge.file_service, "get_project_files_stats", _unexpected_stats)

    response = client.get("/projects/00000000-0000-0000-0000-000000000001/knowledge-base/context")

    assert response.status_code == 200
    assert response.json()["total_files"] == 2
    assert response.json()["total_size"] == 30
    assert [item["file_id"] for item in response.json()["files"]] == ["file-1", "file-2"]


def test_project_knowledge_summary_combines_aggregate_and_processing_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_knowledge_client("owner")

    monkeypatch.setattr(
        projects_core_knowledge.file_service,
        "get_project_file_aggregate_stats",
        lambda *_args, **_kwargs: {
            "total_files": 4,
            "total_size": 400,
            "file_types": {"pdf": 3, "docx": 1},
        },
    )
    monkeypatch.setattr(
        projects_core_knowledge.file_service,
        "get_project_file_processing_status",
        lambda *_args, **_kwargs: {
            "total": 4,
            "pending": 1,
            "processing": 1,
            "completed": 2,
            "failed": 0,
            "all_completed": False,
        },
    )

    response = client.get("/projects/00000000-0000-0000-0000-000000000001/knowledge-base/summary")

    assert response.status_code == 200
    assert response.json() == {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "total_files": 4,
        "total_size": 400,
        "file_types": {"pdf": 3, "docx": 1},
        "pending": 1,
        "processing": 1,
        "completed": 2,
        "failed": 0,
        "all_completed": False,
    }


def test_project_knowledge_files_route_uses_paged_query(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_knowledge_client("owner")

    monkeypatch.setattr(
        projects_core_knowledge.file_service,
        "get_project_file_aggregate_stats",
        lambda *_args, **_kwargs: {
            "total_files": 3,
            "total_size": 30,
            "file_types": {"pdf": 3},
        },
    )

    captured = {"limit": None, "offset": None}

    def _get_page(*_args, **kwargs):  # type: ignore[no-untyped-def]
        captured["limit"] = kwargs.get("limit")
        captured["offset"] = kwargs.get("offset")
        return {
            "files": [
                {
                    "id": "file-2",
                    "project_id": "project-1",
                    "filename": "file-2",
                    "original_filename": "beta.pdf",
                    "file_type": "pdf",
                    "file_size": 20,
                    "created_at": "2026-03-11T01:00:00Z",
                    "updated_at": "2026-03-11T01:00:00Z",
                    "uploaded_by": {
                        "id": "user-1",
                        "name": "User",
                        "email": "user@example.com",
                    },
                    "processing_status": "completed",
                    "indexed_chunk_count": 1,
                    "indexed_at": None,
                    "processing_error": None,
                },
                {
                    "id": "file-1",
                    "project_id": "project-1",
                    "filename": "file-1",
                    "original_filename": "alpha.pdf",
                    "file_type": "pdf",
                    "file_size": 10,
                    "created_at": "2026-03-11T00:00:00Z",
                    "updated_at": "2026-03-11T00:00:00Z",
                    "uploaded_by": {
                        "id": "user-1",
                        "name": "User",
                        "email": "user@example.com",
                    },
                    "processing_status": "completed",
                    "indexed_chunk_count": 1,
                    "indexed_at": None,
                    "processing_error": None,
                },
            ],
            "limit": kwargs.get("limit"),
            "offset": kwargs.get("offset"),
            "total_files": 3,
            "has_more": True,
            "next_offset": 2,
        }

    monkeypatch.setattr(projects_core_knowledge.file_service, "get_project_files_page", _get_page)

    response = client.get("/projects/00000000-0000-0000-0000-000000000001/knowledge-base/files?limit=2&offset=0")

    assert response.status_code == 200
    assert captured == {"limit": 2, "offset": 0}
    payload = response.json()
    assert payload["project_id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["has_more"] is True
    assert payload["next_offset"] == 2
    assert [item["id"] for item in payload["files"]] == ["file-2", "file-1"]


def test_project_knowledge_archive_job_creation_enqueues_outbox_before_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _ArchiveDB(_DB):
        def __init__(self) -> None:
            self.added = []

        def add(self, obj):  # type: ignore[no-untyped-def]
            self.added.append(obj)
            events.append("add")

        def flush(self):  # type: ignore[no-untyped-def]
            events.append("flush")

        def commit(self):  # type: ignore[no-untyped-def]
            events.append("commit")

        def refresh(self, obj):  # type: ignore[no-untyped-def]
            obj.created_at = datetime.now(timezone.utc)
            events.append("refresh")

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
    app.dependency_overrides[projects_core_knowledge.get_db] = lambda: _ArchiveDB()

    monkeypatch.setattr(
        projects_core_knowledge,
        "enqueue_project_archive_outbox_event",
        lambda **_kwargs: events.append("enqueue"),
    )
    monkeypatch.setattr(
        projects_core_knowledge,
        "dispatch_project_archive_outbox_worker",
        lambda: events.append("dispatch"),
    )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/projects/00000000-0000-0000-0000-000000000001/knowledge-base/archive-jobs")

    assert response.status_code == 202
    assert events.index("enqueue") < events.index("commit")
    assert events.index("commit") < events.index("dispatch")
