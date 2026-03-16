from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat.routes import router as chat_router
import app.chat.routes.conversations as conversations_routes


class _FailingAsyncDb:
    async def run_sync(self, _fn):  # type: ignore[no-untyped-def]
        raise AssertionError("db.run_sync should not be called for malformed conversation ids")


async def _async_db_override():
    yield _FailingAsyncDb()


def test_http_get_to_websocket_path_does_not_hit_conversation_lookup() -> None:
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[conversations_routes.get_current_user] = (
        lambda: SimpleNamespace(id="user-1", role="member", name="Test User", email="test@example.com")
    )
    app.dependency_overrides[conversations_routes.get_async_db] = _async_db_override
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/conversations/ws")

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}
