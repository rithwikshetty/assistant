import asyncio
from types import SimpleNamespace

from app.chat.tools.file_tools import execute_read_uploaded_file


class _StubFileService:
    def __init__(self, *, file_row, chunk_by_range):
        self.file_row = file_row
        self.chunk_by_range = chunk_by_range
        self.read_calls = []

    def get_file_by_id(self, file_id, user_id, db):  # type: ignore[no-untyped-def]
        del user_id, db
        if file_id != self.file_row.id:
            return None
        return self.file_row

    def read_file_chunk(self, *, file_id, user_id, start, length, db, allow_full=False):  # type: ignore[no-untyped-def]
        del file_id, user_id, db
        self.read_calls.append({"start": start, "length": length, "allow_full": bool(allow_full)})
        by_full_key = self.chunk_by_range.get((start, length, bool(allow_full)))
        if by_full_key is not None:
            return dict(by_full_key)
        return dict(self.chunk_by_range[(start, length)])


def _build_file_row() -> SimpleNamespace:
    return SimpleNamespace(
        id="file-1",
        filename="system-name.pdf",
        original_filename="knowledge.pdf",
        file_type="pdf",
        file_size=1024,
        extracted_text=None,
        project_id="project-1",
        conversation_id=None,
        child_images=[],
    )


def test_execute_read_uploaded_file_reads_project_single_range() -> None:
    async def _run() -> None:
        file_row = _build_file_row()
        chunk = {
            "file_id": file_row.id,
            "filename": file_row.filename,
            "original_filename": file_row.original_filename,
            "file_type": file_row.file_type,
            "content": "hello world",
            "chunk_start": 0,
            "chunk_end": 11,
            "total_length": 40,
            "has_more": True,
            "encoding": "utf-8",
            "metadata": {"source": "project_file_chunks", "offset_unit": "characters"},
            "checksum": "abc",
            "project_id": file_row.project_id,
            "conversation_id": None,
        }
        file_service = _StubFileService(file_row=file_row, chunk_by_range={(0, 120): chunk})

        response = await execute_read_uploaded_file(
            {"file_id": file_row.id, "start": 0, "length": 120},
            {
                "allowed_file_ids": [file_row.id],
                "file_service": file_service,
                "db": object(),
                "user_id": "user-1",
                "project_id": file_row.project_id,
                "conversation_id": None,
                "max_chunk_length": 500,
            },
        )

        assert response == chunk
        assert file_service.read_calls == [{"start": 0, "length": 120, "allow_full": False}]

    asyncio.run(_run())


def test_execute_read_uploaded_file_reads_project_full_mode() -> None:
    async def _run() -> None:
        file_row = _build_file_row()
        preview_chunk = {
            "file_id": file_row.id,
            "filename": file_row.filename,
            "original_filename": file_row.original_filename,
            "file_type": file_row.file_type,
            "content": "a",
            "chunk_start": 0,
            "chunk_end": 1,
            "total_length": 40,
            "has_more": True,
            "encoding": "utf-8",
            "metadata": {"source": "project_file_chunks", "offset_unit": "characters"},
            "checksum": "abc",
            "project_id": file_row.project_id,
            "conversation_id": None,
        }
        full_chunk = {
            "file_id": file_row.id,
            "filename": file_row.filename,
            "original_filename": file_row.original_filename,
            "file_type": file_row.file_type,
            "content": "x" * 40,
            "chunk_start": 0,
            "chunk_end": 40,
            "total_length": 40,
            "has_more": False,
            "encoding": "utf-8",
            "metadata": {"source": "project_file_chunks", "offset_unit": "characters"},
            "checksum": "abc",
            "project_id": file_row.project_id,
            "conversation_id": None,
        }
        file_service = _StubFileService(
            file_row=file_row,
            chunk_by_range={(0, 1): preview_chunk, (0, 40, True): full_chunk},
        )

        response = await execute_read_uploaded_file(
            {"file_id": file_row.id, "full": True},
            {
                "allowed_file_ids": [file_row.id],
                "file_service": file_service,
                "db": object(),
                "user_id": "user-1",
                "project_id": file_row.project_id,
                "conversation_id": None,
                "max_chunk_length": 500,
            },
        )

        assert response == full_chunk
        assert file_service.read_calls == [
            {"start": 0, "length": 1, "allow_full": False},
            {"start": 0, "length": 40, "allow_full": True},
        ]

    asyncio.run(_run())
