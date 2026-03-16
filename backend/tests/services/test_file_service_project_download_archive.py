from types import SimpleNamespace
import importlib
import zipfile

import pytest

from app.database.models import File
from app.services.files.file_service import FileService

file_service_module = importlib.import_module("app.services.files.file_service")


class _FileQueryStub:
    def __init__(self, rows):  # type: ignore[no-untyped-def]
        self._rows = list(rows)

    def options(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def order_by(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _DBStub:
    def __init__(self, rows):  # type: ignore[no-untyped-def]
        self._rows = list(rows)

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is not File:
            raise AssertionError(f"Unexpected model query: {model}")
        return _FileQueryStub(self._rows)


def test_build_project_files_archive_dedupes_names_and_skips_missing_bytes(monkeypatch) -> None:
    service = FileService()
    rows = [
        SimpleNamespace(id="f-1", filename="blob-1", original_filename="report.pdf"),
        SimpleNamespace(id="f-2", filename="blob-2", original_filename="report.pdf"),
        SimpleNamespace(id="f-3", filename="blob-3", original_filename="notes.txt"),
    ]
    db = _DBStub(rows)

    byte_lookup = {
        "blob-1": b"alpha",
        "blob-2": b"beta",
        "blob-3": None,
    }
    monkeypatch.setattr(
        file_service_module.blob_storage_service,
        "get_bytes",
        lambda filename: byte_lookup.get(filename),
    )

    result = service.build_project_files_archive("project-1234", db)  # type: ignore[arg-type]

    assert result["included"] == 2
    assert result["skipped"] == 1
    assert result["total"] == 3

    archive_file = result["archive_file"]
    with zipfile.ZipFile(archive_file, mode="r") as zip_handle:
        names = sorted(zip_handle.namelist())
        assert "DOWNLOAD_NOTES.txt" in names
        assert "report (2).pdf" in names
        assert "report.pdf" in names
        assert zip_handle.read("report.pdf") == b"alpha"
        assert zip_handle.read("report (2).pdf") == b"beta"

    archive_file.close()


def test_build_project_files_archive_raises_when_project_has_no_files() -> None:
    service = FileService()
    db = _DBStub([])

    with pytest.raises(ValueError, match="No project knowledge files found"):
        service.build_project_files_archive("project-1", db)  # type: ignore[arg-type]
