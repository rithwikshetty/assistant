import asyncio

from app.chat.tools.file_tools import execute_search_project_files


class _StubProjectSearchService:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def __call__(
        self,
        *,
        query,
        project_id,
        db,
        limit,
        user_id=None,
        conversation_id=None,
    ):
        self.calls.append(
            {
                "query": query,
                "project_id": project_id,
                "db": db,
                "limit": limit,
                "user_id": user_id,
                "conversation_id": conversation_id,
            }
        )
        return dict(self.payload)


def test_execute_search_project_files_uses_hybrid_project_search_service() -> None:
    async def _run() -> None:
        payload = {
            "status": "ok",
            "results": [
                {
                    "file_id": "file-1",
                    "filename": "budget.pdf",
                    "file_type": "pdf",
                    "file_size": 1024,
                    "excerpts": ["...budget line item..."],
                    "match_count": 3,
                    "filename_match": True,
                }
            ],
        }
        stub_search_service = _StubProjectSearchService(payload)
        fake_db = object()

        context = {
            "project_id": "project-123",
            "db": fake_db,
            "project_search_service": stub_search_service,
        }

        response = await execute_search_project_files({"query": "budget"}, context)

        assert response["query"] == "budget"
        assert response["message"] == "Found 1 file(s) matching 'budget'"
        assert response["results"] == payload["results"]
        assert stub_search_service.calls == [
            {
                "query": "budget",
                "project_id": "project-123",
                "db": fake_db,
                "limit": 10,
                "user_id": None,
                "conversation_id": None,
            }
        ]

    asyncio.run(_run())


def test_execute_search_project_files_returns_pending_message_when_not_indexed() -> None:
    async def _run() -> None:
        payload = {
            "status": "not_ready",
            "results": [],
            "total_file_count": 4,
            "indexed_file_count": 1,
            "pending_file_count": 3,
        }
        stub_search_service = _StubProjectSearchService(payload)
        context = {
            "project_id": "project-123",
            "db": object(),
            "project_search_service": stub_search_service,
        }

        response = await execute_search_project_files({"query": "contract"}, context)

        assert response == {
            "query": "contract",
            "message": "Project files are still being indexed. 1/4 file(s) indexed, 3 pending.",
            "results": [],
        }
        assert len(stub_search_service.calls) == 1

    asyncio.run(_run())


def test_execute_search_project_files_returns_failed_message_when_all_failed() -> None:
    async def _run() -> None:
        payload = {
            "status": "failed",
            "results": [],
            "total_file_count": 2,
            "indexed_file_count": 0,
            "pending_file_count": 0,
            "failed_file_count": 2,
        }
        stub_search_service = _StubProjectSearchService(payload)
        context = {
            "project_id": "project-123",
            "db": object(),
            "project_search_service": stub_search_service,
        }

        response = await execute_search_project_files({"query": "contract"}, context)

        assert response == {
            "query": "contract",
            "message": "Project file indexing failed before any files were indexed. 2 file(s) failed. Re-upload failed files and retry.",
            "results": [],
        }
        assert len(stub_search_service.calls) == 1

    asyncio.run(_run())
