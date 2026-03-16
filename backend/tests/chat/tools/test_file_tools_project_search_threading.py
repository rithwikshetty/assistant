import asyncio

from app.chat.tools import file_tools


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_execute_search_project_files_default_service_uses_scoped_session(monkeypatch) -> None:
    async def _run() -> None:
        created_sessions: list[_FakeSession] = []
        captured = {}

        def _fake_session_local():
            session = _FakeSession()
            created_sessions.append(session)
            return session

        def _fake_default_service(*, query, project_id, db, limit, user_id, conversation_id):
            captured.update(
                {
                    "query": query,
                    "project_id": project_id,
                    "db": db,
                    "limit": limit,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                }
            )
            return {
                "status": "ok",
                "results": [
                    {
                        "file_id": "file-1",
                        "filename": "budget.pdf",
                        "file_type": "pdf",
                        "file_size": 1024,
                        "excerpts": ["budget"],
                        "match_count": 1,
                        "filename_match": True,
                    }
                ],
            }

        monkeypatch.setattr(file_tools, "SessionLocal", _fake_session_local)
        monkeypatch.setattr(file_tools, "default_project_search_service", _fake_default_service)

        response = await file_tools.execute_search_project_files(
            {"query": "budget", "limit": "bad"},
            {
                "project_id": "project-123",
                "user_id": "user-1",
                "conversation_id": "conv-1",
            },
        )

        assert response["message"] == "Found 1 file(s) matching 'budget'"
        assert len(created_sessions) == 1
        assert created_sessions[0].closed is True
        assert captured["db"] is created_sessions[0]
        assert captured["limit"] == 10
        assert captured["user_id"] == "user-1"
        assert captured["conversation_id"] == "conv-1"

    asyncio.run(_run())
