from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.api import skills as skills_api


class _ManifestQuery:
    def __init__(self, rows):
        self._rows = rows

    def options(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _DownloadQuery:
    def __init__(self, row):
        self._row = row

    def join(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):
        return self._row


class _FakeDB:
    def __init__(self, manifest_rows=None, download_row=None):
        self._manifest_rows = manifest_rows or []
        self._download_row = download_row

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is skills_api.Skill:
            return _ManifestQuery(self._manifest_rows)
        if model is skills_api.SkillFile:
            return _DownloadQuery(self._download_row)
        raise AssertionError(f"Unexpected query model: {model!r}")


def test_get_skills_manifest_reads_db_and_builds_download_paths(monkeypatch) -> None:
    del monkeypatch
    db = _FakeDB(
        manifest_rows=[
            SimpleNamespace(
                skill_id="MY-SKILL",
                title="My Skill",
                description="Skill description",
                when_to_use="When needed",
                content="# My Skill",
                files=[
                    SimpleNamespace(
                        path="references/module a.md",
                        name="module a.md",
                        category="references",
                        size_bytes=17,
                        mime_type="text/markdown",
                    ),
                ],
            )
        ]
    )

    response = Response()
    manifest = skills_api.get_skills_manifest(response=response, user=SimpleNamespace(id="user-1"), db=db)

    assert response.headers.get("cache-control") == "private, max-age=60"
    assert response.headers.get("vary") == "Authorization"
    assert len(manifest["skills"]) == 1
    skill = manifest["skills"][0]
    assert skill["id"] == "my-skill"
    assert skill["source"] == "global"
    assert skill["status"] == "enabled"
    assert "content" not in skill
    assert skill["files"][0]["path"] == "references/module a.md"
    assert skill["files"][0]["download_path"] == "/skills/my-skill/files/references/module%20a.md"


def test_get_skill_detail_returns_content(monkeypatch) -> None:
    del monkeypatch
    db = _FakeDB(
        manifest_rows=[
            SimpleNamespace(
                skill_id="my-skill",
                owner_user_id=None,
                title="My Skill",
                description="Skill description",
                when_to_use="When needed",
                content="# My Skill",
                status="enabled",
            ),
        ]
    )

    detail = skills_api.get_skill_detail(
        skill_id="MY-SKILL",
        user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert detail["id"] == "my-skill"
    assert detail["source"] == "global"
    assert detail["content"] == "# My Skill"


def test_download_skill_file_returns_db_content(monkeypatch) -> None:
    del monkeypatch
    db = _FakeDB(
        download_row=SimpleNamespace(
            name="module.md",
            mime_type="text/markdown",
            binary_content=None,
            text_content="# module",
        )
    )

    response = skills_api.download_skill_file(
        skill_id="MY-SKILL",
        file_path="references/module.md",
        user=SimpleNamespace(id="user-1"),
        db=db,
    )

    assert response.status_code == 200
    assert response.media_type == "text/markdown"
    assert response.body == b"# module"
    assert response.headers.get("content-disposition") == 'attachment; filename="module.md"'


def test_download_skill_file_rejects_unknown_skill(monkeypatch) -> None:
    del monkeypatch
    with pytest.raises(HTTPException) as exc_info:
        skills_api.download_skill_file(
            skill_id="my-skill",
            file_path="references/module.md",
            user=SimpleNamespace(id="user-1"),
            db=_FakeDB(download_row=None),
        )

    assert exc_info.value.status_code == 404


class _WriteDB:
    def __init__(self):
        self.last_added = None
        self.flush_calls = 0
        self.commit_calls = 0

    def add(self, row):  # type: ignore[no-untyped-def]
        self.last_added = row

    def flush(self):
        self.flush_calls += 1

    def commit(self):
        self.commit_calls += 1


def test_create_custom_skill_defaults_to_disabled(monkeypatch) -> None:
    db = _WriteDB()
    created_holder = {"row": None}

    monkeypatch.setattr(skills_api, "_next_custom_skill_id", lambda _db, _user, _preferred: "my-custom")
    monkeypatch.setattr(skills_api, "_upsert_master_skill_file", lambda _row, _owner_user_id: None)

    def _get_created_row(_db, _user, _skill_id):  # type: ignore[no-untyped-def]
        return created_holder["row"]

    monkeypatch.setattr(skills_api, "_get_custom_skill_or_404", _get_created_row)

    payload = skills_api.CustomSkillCreateRequest(title="My Skill")
    user = SimpleNamespace(id="user-1")

    def _capture_add(row):  # type: ignore[no-untyped-def]
        db.last_added = row
        created_holder["row"] = row

    monkeypatch.setattr(db, "add", _capture_add)

    result = skills_api.create_custom_skill(payload=payload, user=user, db=db)

    assert db.last_added is not None
    assert db.last_added.status == "disabled"
    assert db.last_added.skill_id == "my-custom"
    assert result["id"] == "my-custom"
    assert result["status"] == "disabled"
    assert db.flush_calls == 1
    assert db.commit_calls == 1


def test_list_custom_skills_omits_files_in_summary() -> None:
    now = datetime.now(timezone.utc)
    db = _FakeDB(
        manifest_rows=[
            SimpleNamespace(
                skill_id="my-custom",
                title="My Skill",
                description="Skill description",
                when_to_use="When needed",
                status="disabled",
                updated_at=now,
                created_at=now,
                files=[
                    SimpleNamespace(
                        path="assets/template.xlsx",
                        name="template.xlsx",
                        category="assets",
                        size_bytes=120,
                        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                ],
            )
        ]
    )

    response = Response()
    payload = skills_api.list_custom_skills(response=response, user=SimpleNamespace(id="user-1"), db=db)

    assert response.headers.get("cache-control") == "private, no-store"
    assert len(payload["skills"]) == 1
    skill = payload["skills"][0]
    assert skill["id"] == "my-custom"
    assert skill["source"] == "custom"
    assert "files" not in skill


def test_update_custom_skill_rejects_stale_expected_timestamp(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        title="My Skill",
        description="desc",
        when_to_use="when",
        content="# Content",
        status="disabled",
        updated_at=now,
        created_at=now,
        files=[],
    )
    monkeypatch.setattr(skills_api, "_get_custom_skill_or_404", lambda _db, _user, _skill_id: row)

    payload = skills_api.CustomSkillUpdateRequest(
        title="Updated title",
        expected_updated_at=now - timedelta(minutes=2),
    )

    with pytest.raises(HTTPException) as exc_info:
        skills_api.update_custom_skill(
            skill_id="my-custom",
            payload=payload,
            user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 409


class _AsyncDB:
    async def run_sync(self, callback):  # type: ignore[no-untyped-def]
        return callback(self)


@pytest.mark.asyncio
async def test_upload_custom_skill_file_rejects_invalid_category(monkeypatch) -> None:
    row = SimpleNamespace(
        skill_id="my-custom",
        files=[],
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(skills_api, "_get_custom_skill_or_404", lambda _db, _user, _skill_id: row)

    upload = StarletteUploadFile(file=BytesIO(b"abc"), filename="template.xlsx")

    with pytest.raises(HTTPException) as exc_info:
        await skills_api.upload_custom_skill_file(
            skill_id="my-custom",
            file=upload,
            category="other",
            relative_path=None,
            user=SimpleNamespace(id="user-1"),
            db=_AsyncDB(),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_upload_custom_skill_file_rejects_oversized_payload(monkeypatch) -> None:
    row = SimpleNamespace(
        skill_id="my-custom",
        files=[],
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(skills_api, "_get_custom_skill_or_404", lambda _db, _user, _skill_id: row)
    monkeypatch.setattr(skills_api, "_MAX_CUSTOM_SKILL_FILE_BYTES", 5)

    upload = StarletteUploadFile(file=BytesIO(b"abcdef"), filename="template.xlsx")

    with pytest.raises(HTTPException) as exc_info:
        await skills_api.upload_custom_skill_file(
            skill_id="my-custom",
            file=upload,
            category="assets",
            relative_path=None,
            user=SimpleNamespace(id="user-1"),
            db=_AsyncDB(),
        )

    assert exc_info.value.status_code == 413


def test_enable_custom_skill_requires_content(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        title="My Skill",
        description="desc",
        when_to_use="when",
        content="   ",
        status="disabled",
        updated_at=now,
        created_at=now,
        files=[],
    )
    monkeypatch.setattr(skills_api, "_get_custom_skill_or_404", lambda _db, _user, _skill_id: row)

    with pytest.raises(HTTPException) as exc_info:
        skills_api.enable_custom_skill(
            skill_id="my-custom",
            payload=skills_api.CustomSkillActionRequest(),
            user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
