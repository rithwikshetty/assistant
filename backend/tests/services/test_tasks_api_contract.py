from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import tasks as tasks_api


class _DB:
    pass


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(tasks_api.router)
    app.dependency_overrides[tasks_api.get_current_user] = lambda: SimpleNamespace(id="user-1")
    app.dependency_overrides[tasks_api.get_db] = lambda: _DB()
    return TestClient(app, raise_server_exceptions=False)


def test_list_tasks_rejects_invalid_status_filter() -> None:
    client = _build_client()

    response = client.get("/tasks?status=completed")

    assert response.status_code == 422


def test_create_task_rejects_invalid_priority() -> None:
    client = _build_client()

    response = client.post(
        "/tasks",
        json={
            "title": "Ship deployment checklist",
            "priority": "critical",
        },
    )

    assert response.status_code == 422
