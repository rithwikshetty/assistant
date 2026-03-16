from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api import files as files_api


class _ConversationQuery:
    def __init__(self, conversation):
        self._conversation = conversation

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):
        return self._conversation


class _DB:
    def __init__(self, conversation):
        self._conversation = conversation

    def query(self, model):  # type: ignore[no-untyped-def]
        assert model is files_api.Conversation
        return _ConversationQuery(self._conversation)


@pytest.mark.asyncio
async def test_upload_file_preserves_http_status_for_missing_conversation() -> None:
    upload = StarletteUploadFile(filename="doc.txt", file=BytesIO(b"hello"))

    with pytest.raises(HTTPException) as exc_info:
        await files_api.upload_file(
            conversation_id="conv-1",
            file=upload,
            redact=False,
            user=SimpleNamespace(id="user-1"),
            db=_DB(conversation=None),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


@pytest.mark.asyncio
async def test_upload_file_masks_unexpected_processing_errors(monkeypatch) -> None:
    async def _raise_processing_error(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise RuntimeError("storage key leaked")

    monkeypatch.setattr(files_api.file_processing_service, "upload_and_process_file", _raise_processing_error)
    upload = StarletteUploadFile(filename="doc.txt", file=BytesIO(b"hello"))

    with pytest.raises(HTTPException) as exc_info:
        await files_api.upload_file(
            conversation_id="conv-1",
            file=upload,
            redact=False,
            user=SimpleNamespace(id="user-1"),
            db=_DB(conversation=SimpleNamespace(id="conv-1", user_id="user-1")),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to upload file"
