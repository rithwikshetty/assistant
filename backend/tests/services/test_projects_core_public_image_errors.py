from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api import projects_core


class _AsyncDB:
    def __init__(self, *, commit_error: Exception | None = None):
        self._commit_error = commit_error
        self.rollback_calls = 0

    async def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def refresh(self, _project) -> None:  # type: ignore[no-untyped-def]
        return None

    async def run_sync(self, callback):  # type: ignore[no-untyped-def]
        return callback(self)


class _SyncDB:
    def commit(self) -> None:
        return None

    def refresh(self, _project) -> None:  # type: ignore[no-untyped-def]
        return None


def _user() -> SimpleNamespace:
    return SimpleNamespace(id="user-1")


def _project(**overrides) -> SimpleNamespace:
    base = {
        "id": "project-1",
        "is_public_candidate": True,
        "public_image_blob": "public-projects/project-1/old.png",
        "public_image_url": "https://example.com/old.png",
        "public_image_updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_upload_public_project_image_masks_storage_error(monkeypatch) -> None:
    async def _upload_fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError("secret account key")

    monkeypatch.setattr(projects_core, "require_project_owner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(projects_core, "_get_project_for_member", lambda *_args, **_kwargs: _project())
    monkeypatch.setattr(projects_core.blob_storage_service, "upload", _upload_fail)

    upload = StarletteUploadFile(filename="hero.png", file=BytesIO(b"image-bytes"))
    upload.headers = {"content-type": "image/png"}  # type: ignore[attr-defined]

    with pytest.raises(HTTPException) as exc_info:
        await projects_core.upload_public_project_image(
            project_id=uuid4(),
            image=upload,
            user=_user(),
            db=_AsyncDB(),
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to upload image"


@pytest.mark.asyncio
async def test_upload_public_project_image_ignores_previous_blob_delete_failures(monkeypatch) -> None:
    async def _upload_ok(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return "https://example.com/new.png"

    def _delete_fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError("delete failed")

    project = _project()
    monkeypatch.setattr(projects_core, "require_project_owner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(projects_core, "_get_project_for_member", lambda *_args, **_kwargs: project)
    monkeypatch.setattr(projects_core, "_set_current_user_role", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(projects_core.blob_storage_service, "upload", _upload_ok)
    monkeypatch.setattr(projects_core.blob_storage_service, "delete", _delete_fail)

    upload = StarletteUploadFile(filename="hero.png", file=BytesIO(b"image-bytes"))
    upload.headers = {"content-type": "image/png"}  # type: ignore[attr-defined]

    updated = await projects_core.upload_public_project_image(
        project_id=uuid4(),
        image=upload,
        user=_user(),
        db=_AsyncDB(),
    )

    assert updated is project
    assert updated.public_image_blob.endswith(".png")
    assert updated.public_image_url == "https://example.com/new.png"


@pytest.mark.asyncio
async def test_delete_public_project_image_ignores_blob_delete_failures(monkeypatch) -> None:
    def _delete_fail(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        raise RuntimeError("delete failed")

    project = _project()
    monkeypatch.setattr(projects_core, "require_project_owner", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(projects_core, "_get_project_for_member", lambda *_args, **_kwargs: project)
    monkeypatch.setattr(projects_core, "_set_current_user_role", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(projects_core.blob_storage_service, "delete", _delete_fail)

    updated = projects_core.delete_public_project_image(
        project_id=uuid4(),
        user=_user(),
        db=_SyncDB(),
    )

    assert updated is project
    assert updated.public_image_blob is None
    assert updated.public_image_url is None
