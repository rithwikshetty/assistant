import asyncio
from types import SimpleNamespace

from app.chat.tools import code_execution


def test_execute_code_loads_skill_asset_from_db(monkeypatch) -> None:
    async def _run() -> None:
        captured = {"input_files": []}

        async def _fake_execute_code(*, code, input_files=None, timeout=60, session_id="default"):  # type: ignore[no-untyped-def]
            del code, timeout
            captured["input_files"] = list(input_files or [])
            return SimpleNamespace(
                success=True,
                stdout="ok",
                stderr="",
                exit_code=0,
                execution_time_ms=5,
                output_files=[],
                error=None,
            )

        monkeypatch.setattr(
            code_execution,
            "get_active_skill_asset_bytes",
            lambda db, asset_ref, **kwargs: ("template.xlsx", b"seed-bytes")
            if asset_ref == "oce-generator/assets/TEM-1_Template.xlsx"
            else None,
        )
        monkeypatch.setattr(code_execution.code_execution_service, "execute_code", _fake_execute_code)

        result = await code_execution.execute_code_tool(
            {
                "code": "print('hello')",
                "skill_assets": ["oce-generator/assets/TEM-1_Template.xlsx"],
            },
            {
                "user_id": "user-1",
                "conversation_id": "conv-1",
                "db": object(),
            },
        )

        assert result["success"] is True
        assert len(captured["input_files"]) == 1
        assert captured["input_files"][0].filename == "template.xlsx"
        assert captured["input_files"][0].data == b"seed-bytes"

    asyncio.run(_run())


def test_execute_code_batches_file_id_lookup(monkeypatch) -> None:
    async def _run() -> None:
        captured = {"input_files": []}

        class _FileQueryStub:
            def __init__(self, rows):  # type: ignore[no-untyped-def]
                self._rows = rows

            def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
                del args, kwargs
                return self

            def all(self):  # type: ignore[no-untyped-def]
                return list(self._rows)

        class _DBStub:
            def __init__(self):  # type: ignore[no-untyped-def]
                self.query_calls = 0

            def query(self, _model):  # type: ignore[no-untyped-def]
                self.query_calls += 1
                return _FileQueryStub(
                    [
                        SimpleNamespace(id="file-1", filename="blob-1", original_filename="one.csv"),
                        SimpleNamespace(id="file-2", filename="blob-2", original_filename="two.csv"),
                    ]
                )

        async def _fake_execute_code(*, code, input_files=None, timeout=60, session_id="default"):  # type: ignore[no-untyped-def]
            del code, timeout, session_id
            captured["input_files"] = list(input_files or [])
            return SimpleNamespace(
                success=True,
                stdout="ok",
                stderr="",
                exit_code=0,
                execution_time_ms=5,
                output_files=[],
                error=None,
            )

        db = _DBStub()
        monkeypatch.setattr(code_execution.code_execution_service, "execute_code", _fake_execute_code)
        monkeypatch.setattr(
            code_execution.blob_storage_service,
            "get_bytes",
            lambda filename: b"one" if filename == "blob-1" else b"two" if filename == "blob-2" else None,
        )

        result = await code_execution.execute_code_tool(
            {
                "code": "print('hello')",
                "file_ids": ["file-1", "missing", "file-2"],
            },
            {
                "user_id": "user-1",
                "conversation_id": "conv-1",
                "db": db,
            },
        )

        assert result["success"] is True
        assert db.query_calls == 1
        assert [f.filename for f in captured["input_files"]] == ["one.csv", "two.csv"]

    asyncio.run(_run())
