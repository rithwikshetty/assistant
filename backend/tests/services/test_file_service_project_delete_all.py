from types import SimpleNamespace
import importlib

from app.database.models import BlobObject, Conversation, File, ProjectFileChunk, ProjectFileIndexOutbox, StagedFile
from app.services.files.file_service import FileService

file_service_module = importlib.import_module("app.services.files.file_service")


class _DeleteQueryStub:
    def __init__(self, db, key):  # type: ignore[no-untyped-def]
        self._db = db
        self._key = key

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def delete(self, synchronize_session=False):  # type: ignore[no-untyped-def]
        del synchronize_session
        self._db.delete_counts[self._key] += 1
        return 0


class _FileQueryStub:
    def __init__(self, rows):  # type: ignore[no-untyped-def]
        self._rows = list(rows)

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _DBStub:
    def __init__(self, *, top_level, children):  # type: ignore[no-untyped-def]
        self._top_level = list(top_level)
        self._children = list(children)
        self._file_query_calls = 0
        self.delete_counts = {"chunks": 0, "outbox": 0}
        self.deleted = []
        self.commit_count = 0

    def query(self, model):  # type: ignore[no-untyped-def]
        if model is File:
            self._file_query_calls += 1
            if self._file_query_calls == 1:
                return _FileQueryStub(self._top_level)
            return _FileQueryStub(self._children)
        if model is ProjectFileChunk:
            return _DeleteQueryStub(self, "chunks")
        if model is ProjectFileIndexOutbox:
            return _DeleteQueryStub(self, "outbox")
        raise AssertionError(f"Unexpected model query: {model}")

    def delete(self, item):  # type: ignore[no-untyped-def]
        self.deleted.append(item)

    def commit(self):  # type: ignore[no-untyped-def]
        self.commit_count += 1

    def flush(self):  # type: ignore[no-untyped-def]
        return None


class _DeleteFileDBStub:
    def __init__(self, *, children, blob_objects):  # type: ignore[no-untyped-def]
        self._children = list(children)
        self._blob_objects = list(blob_objects)
        self.deleted = []
        self.commit_count = 0

    def query(self, *args):  # type: ignore[no-untyped-def]
        if len(args) == 1 and args[0] is File:
            return _FileQueryStub(self._children)
        if len(args) == 1 and args[0] is BlobObject:
            return _FileQueryStub(self._blob_objects)
        if len(args) == 1 and getattr(args[0], "key", "") == "blob_object_id":
            parent = getattr(args[0], "parent", None)
            parent_name = getattr(parent, "class_", None)
            if parent_name is File:
                return _FileQueryStub([])
            if parent_name is StagedFile:
                return _FileQueryStub([])
        raise AssertionError(f"Unexpected query args: {args}")

    def delete(self, item):  # type: ignore[no-untyped-def]
        self.deleted.append(item)

    def commit(self):  # type: ignore[no-untyped-def]
        self.commit_count += 1

    def flush(self):  # type: ignore[no-untyped-def]
        return None


class _PurgeQueryStub:
    def __init__(self, rows):  # type: ignore[no-untyped-def]
        self._rows = list(rows)

    def join(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def outerjoin(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def filter(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return list(self._rows)


class _PurgeDBStub:
    def __init__(self, *, conversation_id_queries, blob_id_queries, blob_rows):  # type: ignore[no-untyped-def]
        self._conversation_id_queries = list(conversation_id_queries)
        self._blob_id_queries = list(blob_id_queries)
        self._blob_rows = list(blob_rows)
        self.commit_count = 0

    def query(self, *args):  # type: ignore[no-untyped-def]
        if len(args) != 1:
            raise AssertionError(f"Unexpected query args: {args}")
        model_or_column = args[0]
        if model_or_column is BlobObject:
            return _PurgeQueryStub(self._blob_rows)
        if getattr(model_or_column, "key", "") == "id":
            parent = getattr(model_or_column, "parent", None)
            parent_name = getattr(parent, "class_", None)
            if parent_name is Conversation:
                if not self._conversation_id_queries:
                    raise AssertionError("Unexpected conversation id query")
                return _PurgeQueryStub(self._conversation_id_queries.pop(0))
        if getattr(model_or_column, "key", "") == "blob_object_id":
            if not self._blob_id_queries:
                raise AssertionError("Unexpected blob_object_id query")
            return _PurgeQueryStub(self._blob_id_queries.pop(0))
        raise AssertionError(f"Unexpected query target: {model_or_column}")

    def commit(self):  # type: ignore[no-untyped-def]
        self.commit_count += 1

    def rollback(self):  # type: ignore[no-untyped-def]
        self.rollback_count = getattr(self, "rollback_count", 0) + 1


def test_delete_project_files_deletes_chunks_outbox_children_and_parents(monkeypatch) -> None:
    service = FileService()
    parent_a = SimpleNamespace(id="parent-a", filename="a.pdf")
    parent_b = SimpleNamespace(id="parent-b", filename="b.pdf")
    child_a = SimpleNamespace(id="child-a", parent_file_id="parent-a", filename="a-image.png")
    db = _DBStub(top_level=[parent_a, parent_b], children=[child_a])

    monkeypatch.setattr(file_service_module.blob_storage_service, "blob_client", None)

    deleted_count = service.delete_project_files("project-1", db)  # type: ignore[arg-type]

    assert deleted_count == 2
    assert db.delete_counts == {"chunks": 1, "outbox": 1}
    assert db.deleted == [child_a, parent_a, parent_b]
    assert db.commit_count == 1


def test_delete_project_files_returns_zero_when_project_has_no_files(monkeypatch) -> None:
    service = FileService()
    db = _DBStub(top_level=[], children=[])

    monkeypatch.setattr(file_service_module.blob_storage_service, "blob_client", None)

    deleted_count = service.delete_project_files("project-1", db)  # type: ignore[arg-type]

    assert deleted_count == 0
    assert db.delete_counts == {"chunks": 0, "outbox": 0}
    assert db.deleted == []
    assert db.commit_count == 0


def test_delete_file_deletes_all_related_blobs_without_reference_queries(monkeypatch) -> None:
    service = FileService()
    parent = SimpleNamespace(id="parent-1", filename="shared.pdf")
    child_keep = SimpleNamespace(id="child-1", parent_file_id="parent-1", filename="shared.pdf")
    child_delete = SimpleNamespace(id="child-2", parent_file_id="parent-1", filename="child-a.png")
    blob_child = SimpleNamespace(id="blob-2", storage_key="child-a.png")
    blob_parent = SimpleNamespace(id="blob-1", storage_key="shared.pdf")
    parent.blob_object_id = "blob-1"
    child_keep.blob_object_id = "blob-1"
    child_delete.blob_object_id = "blob-2"
    db = _DeleteFileDBStub(children=[child_keep, child_delete], blob_objects=[blob_parent, blob_child])

    deleted_blobs = []
    monkeypatch.setattr(file_service_module.blob_storage_service, "blob_client", object())
    monkeypatch.setattr(
        file_service_module.blob_storage_service,
        "delete",
        lambda filename: (deleted_blobs.append(filename), True)[1],
    )
    monkeypatch.setattr(service, "get_file_by_id", lambda file_id, user_id, db_arg: parent)

    deleted = service.delete_file("parent-1", "user-1", db)  # type: ignore[arg-type]

    assert deleted is True
    assert sorted(deleted_blobs) == ["child-a.png", "shared.pdf"]
    assert child_keep in db.deleted
    assert child_delete in db.deleted
    assert parent in db.deleted
    assert blob_parent in db.deleted
    assert blob_child in db.deleted
    assert len(db.deleted) == 5
    assert db.commit_count == 1


def test_purge_archived_conversation_blob_content_marks_unreferenced_blobs(monkeypatch) -> None:
    service = FileService()
    blob_row = SimpleNamespace(id="blob-a", storage_key="archived-only.pdf", purged_at=None)
    db = _PurgeDBStub(
        conversation_id_queries=[],
        blob_id_queries=[
            [("blob-a",), ("blob-b",)],  # candidates from archived conversation files
            [("blob-b",)],  # active conversation refs (should be excluded)
            [],  # project refs
            [],  # staged refs
        ],
        blob_rows=[blob_row],
    )

    deleted = []
    monkeypatch.setattr(
        file_service_module.blob_storage_service,
        "delete",
        lambda filename: (deleted.append(filename), True)[1],
    )

    purged = service.purge_archived_conversation_blob_content(
        db=db,  # type: ignore[arg-type]
        conversation_ids=["conversation-1"],
        commit=False,
    )

    assert purged == 1
    assert deleted == ["archived-only.pdf"]
    assert blob_row.purged_at is not None
    assert db.commit_count == 0


def test_purge_archived_conversation_blob_content_skips_when_delete_fails(monkeypatch) -> None:
    service = FileService()
    blob_row = SimpleNamespace(id="blob-a", storage_key="archived-only.pdf", purged_at=None)
    db = _PurgeDBStub(
        conversation_id_queries=[],
        blob_id_queries=[
            [("blob-a",)],
            [],
            [],
            [],
        ],
        blob_rows=[blob_row],
    )

    monkeypatch.setattr(file_service_module.blob_storage_service, "delete", lambda filename: False)

    purged = service.purge_archived_conversation_blob_content(
        db=db,  # type: ignore[arg-type]
        conversation_ids=["conversation-1"],
        commit=True,
    )

    assert purged == 0
    assert blob_row.purged_at is None
    assert db.commit_count == 0


def test_purge_archived_project_blob_content_marks_project_scoped_blobs(monkeypatch) -> None:
    service = FileService()
    blob_row = SimpleNamespace(id="blob-a", storage_key="project-only.pdf", purged_at=None)
    db = _PurgeDBStub(
        conversation_id_queries=[
            [("conversation-1",)],
        ],
        blob_id_queries=[
            [("blob-a",)],  # project-scoped file candidates
            [],  # archived project conversation file candidates
            [],  # blocking refs outside target archived project scope
            [],  # staged refs
        ],
        blob_rows=[blob_row],
    )

    deleted = []
    monkeypatch.setattr(
        file_service_module.blob_storage_service,
        "delete",
        lambda filename: (deleted.append(filename), True)[1],
    )

    purged = service.purge_archived_project_blob_content(
        db=db,  # type: ignore[arg-type]
        project_ids=["project-1"],
        commit=False,
    )

    assert purged == 1
    assert deleted == ["project-only.pdf"]
    assert blob_row.purged_at is not None
    assert db.commit_count == 0


def test_purge_archived_project_blob_content_respects_blocking_refs(monkeypatch) -> None:
    service = FileService()
    blob_row = SimpleNamespace(id="blob-a", storage_key="shared.pdf", purged_at=None)
    db = _PurgeDBStub(
        conversation_id_queries=[
            [("conversation-1",)],
        ],
        blob_id_queries=[
            [("blob-a",)],
            [],
            [("blob-a",)],  # blocked by out-of-scope active ref
            [],
        ],
        blob_rows=[blob_row],
    )

    monkeypatch.setattr(file_service_module.blob_storage_service, "delete", lambda filename: True)

    purged = service.purge_archived_project_blob_content(
        db=db,  # type: ignore[arg-type]
        project_ids=["project-1"],
        commit=True,
    )

    assert purged == 0
    assert blob_row.purged_at is None
    assert db.commit_count == 0


def test_purge_archived_conversation_blob_content_best_effort_rolls_back_and_returns_zero(monkeypatch) -> None:
    service = FileService()
    db = _PurgeDBStub(
        conversation_id_queries=[],
        blob_id_queries=[],
        blob_rows=[],
    )

    def _raise_error(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "purge_archived_conversation_blob_content", _raise_error)

    purged = service.purge_archived_conversation_blob_content_best_effort(
        db=db,  # type: ignore[arg-type]
        conversation_ids=["conversation-1"],
        user_id="user-1",
    )

    assert purged == 0
    assert getattr(db, "rollback_count", 0) == 1


def test_purge_archived_project_blob_content_best_effort_rolls_back_and_returns_zero(monkeypatch) -> None:
    service = FileService()
    db = _PurgeDBStub(
        conversation_id_queries=[],
        blob_id_queries=[],
        blob_rows=[],
    )

    def _raise_error(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "purge_archived_project_blob_content", _raise_error)

    purged = service.purge_archived_project_blob_content_best_effort(
        db=db,  # type: ignore[arg-type]
        project_ids=["project-1"],
        user_id="user-1",
    )

    assert purged == 0
    assert getattr(db, "rollback_count", 0) == 1
