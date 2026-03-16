from types import SimpleNamespace

import pytest

from app.chat.skills import store


def test_discover_builtin_skills_reads_frontmatter_and_files(tmp_path) -> None:
    skill_dir = tmp_path / "rate-helper"
    skill_dir.mkdir()
    (skill_dir / "assets").mkdir()
    (skill_dir / "references").mkdir()

    (skill_dir / "SKILL.md").write_text(
        """---
name: rate-helper
description: Helper skill
when_to_use: Use for rates
---
# Rate Helper

Load `references/module_a.md` first.
""",
        encoding="utf-8",
    )
    (skill_dir / "references" / "module_a.md").write_text("# Module A\n\nUse this module.", encoding="utf-8")
    (skill_dir / "assets" / "template.xlsx").write_bytes(b"\x50\x4b\x03\x04")

    discovered = store.discover_builtin_skills(tmp_path)

    assert len(discovered) == 1
    skill = discovered[0]
    assert skill.skill_id == "rate-helper"
    assert skill.description == "Helper skill"
    assert skill.when_to_use == "Use for rates"
    assert skill.content.startswith("# Rate Helper")

    by_path = {item.path: item for item in skill.files}
    assert "SKILL.md" in by_path
    assert "references/module_a.md" in by_path
    assert "assets/template.xlsx" in by_path
    assert by_path["references/module_a.md"].category == "references"
    assert by_path["assets/template.xlsx"].binary_content == b"\x50\x4b\x03\x04"


def test_discover_builtin_skills_ignores_hidden_files(tmp_path) -> None:
    skill_dir = tmp_path / "rate-helper"
    skill_dir.mkdir()
    (skill_dir / "references").mkdir()

    (skill_dir / "SKILL.md").write_text(
        """---
name: rate-helper
description: Helper skill
when_to_use: Use for rates
---
# Rate Helper
""",
        encoding="utf-8",
    )
    (skill_dir / "references" / "module_a.md").write_text("# Module A\n\nUse this module.", encoding="utf-8")
    (skill_dir / ".DS_Store").write_bytes(b"ignored")
    (skill_dir / "references" / ".DS_Store").write_bytes(b"ignored")

    discovered = store.discover_builtin_skills(tmp_path)

    assert len(discovered) == 1
    paths = {item.path for item in discovered[0].files}
    assert "SKILL.md" in paths
    assert "references/module_a.md" in paths
    assert ".DS_Store" not in paths
    assert "references/.DS_Store" not in paths


def test_get_active_skill_asset_bytes_returns_binary(monkeypatch) -> None:
    monkeypatch.setattr(
        store,
        "get_active_skill_file",
        lambda db, skill_id, relative_path, **kwargs: SimpleNamespace(
            name="template.xlsx",
            binary_content=b"abc",
            text_content=None,
        ),
    )

    resolved = store.get_active_skill_asset_bytes(object(), "rate-helper/assets/template.xlsx")

    assert resolved == ("template.xlsx", b"abc")


def test_get_active_skill_asset_bytes_rejects_path_traversal(monkeypatch) -> None:
    called = {"value": False}

    def _fake_get_active_skill_file(db, skill_id, relative_path, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        called["value"] = True
        return None

    monkeypatch.setattr(store, "get_active_skill_file", _fake_get_active_skill_file)

    resolved = store.get_active_skill_asset_bytes(object(), "rate-helper/../secrets.txt")

    assert resolved is None
    assert called["value"] is False


def test_get_active_skill_asset_bytes_reads_blob_backed_file(monkeypatch) -> None:
    monkeypatch.setattr(
        store,
        "get_active_skill_file",
        lambda db, skill_id, relative_path, **kwargs: SimpleNamespace(
            name="template.xlsx",
            storage_backend="blob",
            blob_path="skills/global/rate-helper/template.xlsx",
            binary_content=None,
            text_content=None,
        ),
    )
    monkeypatch.setattr(
        store.blob_storage_service,
        "get_bytes",
        lambda blob_path: b"blob-bytes" if blob_path == "skills/global/rate-helper/template.xlsx" else None,
    )

    resolved = store.get_active_skill_asset_bytes(object(), "rate-helper/assets/template.xlsx")

    assert resolved == ("template.xlsx", b"blob-bytes")


def test_upsert_skill_file_from_bytes_updates_existing_row_in_place(monkeypatch) -> None:
    deleted = {"blob_paths": []}

    monkeypatch.setattr(
        store,
        "_delete_skill_file_blob",
        lambda file_row: deleted["blob_paths"].append(getattr(file_row, "blob_path", "")),
    )

    existing = SimpleNamespace(
        path="SKILL.md",
        name="SKILL.md",
        category="skill",
        mime_type="text/markdown",
        storage_backend="db",
        blob_path=None,
        text_content="# Old",
        binary_content=None,
        size_bytes=5,
        checksum_sha256="deadbeef",
    )
    skill_row = SimpleNamespace(
        skill_id="rate-helper",
        files=[existing],
    )

    written = store.upsert_skill_file_from_bytes(
        skill_row=skill_row,
        owner_user_id="user-1",
        relative_path="SKILL.md",
        raw_bytes=b"# Updated\n\nInstructions",
        category_override="skill",
        mime_type_override="text/markdown",
    )

    assert deleted["blob_paths"] == []
    assert len(skill_row.files) == 1
    assert written is existing
    assert written.path == "SKILL.md"
    assert written.category == "skill"
    assert written.text_content.startswith("# Updated")


def test_upsert_skill_file_from_bytes_deletes_replaced_blob_path(monkeypatch) -> None:
    deleted = {"blob_paths": []}
    monkeypatch.setattr(
        store,
        "_delete_skill_file_blob",
        lambda file_row: deleted["blob_paths"].append(getattr(file_row, "blob_path", "")),
    )

    existing = SimpleNamespace(
        path="references/module_a.md",
        name="module_a.md",
        category="references",
        mime_type="text/markdown",
        storage_backend="blob",
        blob_path="skills/user/user-1/rate-helper/old.md",
        text_content=None,
        binary_content=None,
        size_bytes=10,
        checksum_sha256="old",
    )
    skill_row = SimpleNamespace(skill_id="rate-helper", files=[existing])

    written = store.upsert_skill_file_from_bytes(
        skill_row=skill_row,
        owner_user_id="user-1",
        relative_path="references/module_a.md",
        raw_bytes=b"# Module A\\n\\nUpdated",
        category_override="references",
        mime_type_override="text/markdown",
    )

    assert len(skill_row.files) == 1
    assert written is existing
    assert deleted["blob_paths"] == ["skills/user/user-1/rate-helper/old.md"]
    assert written.storage_backend == "db"


def test_remove_skill_file_by_path_removes_matching_file(monkeypatch) -> None:
    deleted = {"paths": []}
    monkeypatch.setattr(
        store,
        "_delete_skill_file_blob",
        lambda file_row: deleted["paths"].append(getattr(file_row, "path", "")),
    )

    existing = SimpleNamespace(path="assets/template.xlsx", name="template.xlsx")
    skill_row = SimpleNamespace(skill_id="rate-helper", files=[existing])

    removed = store.remove_skill_file_by_path(skill_row, "assets/template.xlsx")

    assert removed is True
    assert deleted["paths"] == ["assets/template.xlsx"]
    assert skill_row.files == []


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, *columns):  # type: ignore[no-untyped-def]
        del columns
        return _FakeQuery(self._rows)


def test_build_skills_prompt_section_from_db_filters_by_allowed_ids() -> None:
    db = _FakeDB([
        ("cost-estimation", "Cost desc", "Use for cost"),
        ("tone-of-voice", "Tone desc", "Use for writing"),
    ])

    section = store.build_skills_prompt_section_from_db(db, {"cost-estimation"})

    assert "- cost-estimation: Cost desc" in section
    assert "- cost-estimation: Use for cost" in section
    assert "tone-of-voice" not in section


class _FakeAsyncResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeAsyncDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):  # type: ignore[no-untyped-def]
        del stmt
        return _FakeAsyncResult(self._rows)


@pytest.mark.asyncio
async def test_build_skills_prompt_section_from_db_async_filters_by_allowed_ids() -> None:
    db = _FakeAsyncDB([
        ("cost-estimation", "Cost desc", "Use for cost", None),
        ("tone-of-voice", "Tone desc", "Use for writing", None),
    ])

    section = await store.build_skills_prompt_section_from_db_async(db, {"cost-estimation"})

    assert "- cost-estimation: Cost desc" in section
    assert "- cost-estimation: Use for cost" in section
    assert "tone-of-voice" not in section


class _CountQuery:
    def __init__(self, count_value: int):
        self._count_value = count_value

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def count(self) -> int:
        return self._count_value


class _CountDB:
    def __init__(self, count_value: int):
        self._count_value = count_value

    def query(self, *columns):  # type: ignore[no-untyped-def]
        del columns
        return _CountQuery(self._count_value)


def test_ensure_builtin_skills_seeded_skips_when_builtin_rows_exist(monkeypatch) -> None:
    called = {"value": False}

    def _fake_upsert(db, skills_root=None):  # type: ignore[no-untyped-def]
        del db, skills_root
        called["value"] = True
        return {
            "skills_discovered": 1,
            "skills_inserted": 1,
            "skills_updated": 0,
            "skills_deleted": 0,
            "files_written": 2,
        }

    monkeypatch.setattr(store, "upsert_builtin_skills_from_filesystem", _fake_upsert)
    stats = store.ensure_builtin_skills_seeded(_CountDB(3))

    assert stats["existing_builtin_skills"] == 3
    assert stats["seeded"] == 0
    assert called["value"] is False


def test_ensure_builtin_skills_seeded_runs_when_builtin_rows_missing(monkeypatch) -> None:
    called = {"value": False}

    def _fake_upsert(db, skills_root=None):  # type: ignore[no-untyped-def]
        del db, skills_root
        called["value"] = True
        return {
            "skills_discovered": 2,
            "skills_inserted": 2,
            "skills_updated": 0,
            "skills_deleted": 0,
            "files_written": 5,
        }

    monkeypatch.setattr(store, "upsert_builtin_skills_from_filesystem", _fake_upsert)
    stats = store.ensure_builtin_skills_seeded(_CountDB(0))

    assert called["value"] is True
    assert stats["existing_builtin_skills"] == 0
    assert stats["seeded"] == 1
    assert stats["skills_inserted"] == 2
