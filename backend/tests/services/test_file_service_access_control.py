from types import SimpleNamespace

from app.database.models import File
from app.services.files.file_service import FileService


class _FileAccessQueryStub:
    def __init__(self, row):  # type: ignore[no-untyped-def]
        self._row = row

    def options(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def outerjoin(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def first(self):  # type: ignore[no-untyped-def]
        return self._row


class _AccessDBStub:
    def __init__(self, row):  # type: ignore[no-untyped-def]
        self._row = row
        self.query_calls = []

    def query(self, model):  # type: ignore[no-untyped-def]
        self.query_calls.append(model)
        if model is File:
            return _FileAccessQueryStub(self._row)
        raise AssertionError(f"Unexpected model query: {model}")


def test_get_file_by_id_project_member_path_uses_single_joined_query() -> None:
    service = FileService()
    file_row = SimpleNamespace(id="file-1", user_id="owner-1", project_id="project-1")
    db = _AccessDBStub(file_row)

    result = service.get_file_by_id(file_id="file-1", user_id="member-1", db=db)  # type: ignore[arg-type]

    assert result is file_row
    assert db.query_calls == [File]
