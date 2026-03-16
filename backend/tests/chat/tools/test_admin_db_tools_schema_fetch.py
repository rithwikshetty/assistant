from types import SimpleNamespace

import pytest

from app.chat.tools import admin_db_tools


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self) -> None:
        self.bind = object()
        self.calls = []

    def execute(self, stmt, params=None):  # noqa: ANN001
        sql = str(stmt)
        self.calls.append(sql)
        if "FROM pg_catalog.pg_class c" in sql and "FROM pg_catalog.pg_attribute a" not in sql:
            return _FakeResult(
                [
                    ("public", "users"),
                    ("public", "messages"),
                ]
            )
        if "FROM pg_catalog.pg_attribute a" in sql:
            return _FakeResult(
                [
                    ("public", "messages", "id", "uuid", False),
                    ("public", "messages", "user_id", "uuid", True),
                    ("public", "users", "id", "uuid", False),
                    ("public", "users", "email", "text", False),
                ]
            )
        raise AssertionError(f"Unexpected SQL executed: {sql}")


def test_get_database_schema_catalog_fallback_batches_column_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_inspector = SimpleNamespace(
        get_table_names=lambda schema=None: [],
        get_columns=lambda table_name, schema=None: [],
        get_indexes=lambda table_name: [],
        get_foreign_keys=lambda table_name: [],
    )
    monkeypatch.setattr(admin_db_tools, "inspect", lambda _bind: fake_inspector)

    session = _FakeSession()
    payload = admin_db_tools.get_database_schema(session)

    assert payload["database_type"] == "PostgreSQL"
    assert payload["table_count"] == 2
    assert {row["table_name"] for row in payload["tables"]} == {"public.users", "public.messages"}

    attribute_query_calls = [sql for sql in session.calls if "FROM pg_catalog.pg_attribute a" in sql]
    assert len(attribute_query_calls) == 1
