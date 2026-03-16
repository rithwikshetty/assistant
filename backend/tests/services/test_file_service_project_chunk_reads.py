from types import SimpleNamespace

import pytest

from app.database.models import ProjectFileChunk
from app.services.files.file_service import FileService


class _ScalarQueryStub:
    def __init__(self, value):
        self._value = value

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def scalar(self):  # type: ignore[no-untyped-def]
        return self._value


class _ChunkQueryStub:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._chunks)


class _DBStub:
    def __init__(self, *, total_length, chunks):
        self._total_length = total_length
        self._chunks = chunks

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is ProjectFileChunk:
            return _ChunkQueryStub(self._chunks)
        return _ScalarQueryStub(self._total_length)


def test_read_file_chunk_reconstructs_project_content_from_overlapping_chunks(monkeypatch) -> None:
    service = FileService()
    file_row = SimpleNamespace(
        id="file-1",
        filename="system.pdf",
        original_filename="doc.pdf",
        file_type="pdf",
        project_id="project-1",
        conversation_id=None,
        content_hash="abc123",
    )

    chunks = [
        SimpleNamespace(chunk_index=0, char_start=0, char_end=10, chunk_text="abcdefghij"),
        SimpleNamespace(chunk_index=1, char_start=8, char_end=18, chunk_text="ijKLMNOPQR"),
    ]
    db = _DBStub(total_length=18, chunks=chunks)

    monkeypatch.setattr(service, "get_file_by_id", lambda file_id, user_id, db, **kw: file_row)

    result = service.read_file_chunk(
        file_id="file-1",
        user_id="user-1",
        start=5,
        length=10,
        db=db,  # type: ignore[arg-type]
    )

    assert result["content"] == "fghijKLMNO"
    assert result["chunk_start"] == 5
    assert result["chunk_end"] == 15
    assert result["total_length"] == 18
    assert result["has_more"] is True
    assert result["metadata"]["source"] == "project_file_chunks"


def test_read_file_chunk_raises_when_project_chunks_not_ready(monkeypatch) -> None:
    service = FileService()
    file_row = SimpleNamespace(
        id="file-2",
        filename="system.pdf",
        original_filename="doc.pdf",
        file_type="pdf",
        project_id="project-2",
        conversation_id=None,
        content_hash="def456",
    )
    db = _DBStub(total_length=0, chunks=[])

    monkeypatch.setattr(service, "get_file_by_id", lambda file_id, user_id, db, **kw: file_row)

    with pytest.raises(RuntimeError, match="not indexed yet"):
        service.read_file_chunk(
            file_id="file-2",
            user_id="user-1",
            start=0,
            length=200,
            db=db,  # type: ignore[arg-type]
        )
