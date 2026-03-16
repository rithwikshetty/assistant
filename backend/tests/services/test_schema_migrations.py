from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.database.migrations import (
    MIGRATIONS_TABLE,
    _split_sql_statements,
    apply_schema_migrations,
    latest_migration_version,
    list_migration_files,
)


def _write_migration(migrations_dir: Path, filename: str, sql_text: str) -> None:
    migrations_dir.mkdir(parents=True, exist_ok=True)
    (migrations_dir / filename).write_text(sql_text, encoding="utf-8")


def test_list_migration_files_sorts_versions_numerically(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0010_ten.sql", "SELECT 10;")
    _write_migration(tmp_path, "0002_two.sql", "SELECT 2;")
    _write_migration(tmp_path, "0001_one.sql", "SELECT 1;")

    migrations = list_migration_files(tmp_path)

    assert [migration.version for migration in migrations] == ["0001", "0002", "0010"]
    assert latest_migration_version(tmp_path) == "0010"


def test_list_migration_files_rejects_duplicate_versions(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_one.sql", "SELECT 1;")
    _write_migration(tmp_path, "0001_duplicate.sql", "SELECT 2;")

    with pytest.raises(ValueError, match="Duplicate migration version 0001"):
        list_migration_files(tmp_path)


def test_split_sql_statements_keeps_semicolons_inside_quotes_and_comments() -> None:
    sql_text = """
    -- comment with ; should not split
    CREATE TABLE example (
        id INTEGER PRIMARY KEY,
        note TEXT DEFAULT 'semi;colon'
    );
    INSERT INTO example(note) VALUES ('still;one;statement');
    DO $block$
    BEGIN
        PERFORM 'ignored;split';
    END
    $block$;
    """

    statements = _split_sql_statements(sql_text)

    assert statements == [
        """-- comment with ; should not split
    CREATE TABLE example (
        id INTEGER PRIMARY KEY,
        note TEXT DEFAULT 'semi;colon'
    )""",
        "INSERT INTO example(note) VALUES ('still;one;statement')",
        """DO $block$
    BEGIN
        PERFORM 'ignored;split';
    END
    $block$""",
    ]


def test_apply_schema_migrations_applies_pending_versions_once(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_migration(
        migrations_dir,
        "0001_create_widgets.sql",
        """
        CREATE TABLE widgets (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        """,
    )
    _write_migration(
        migrations_dir,
        "0002_seed_widgets.sql",
        """
        INSERT INTO widgets (id, name) VALUES (1, 'alpha');
        INSERT INTO widgets (id, name) VALUES (2, 'beta');
        """,
    )

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'migrations.db'}")
    try:
        executed = apply_schema_migrations(engine=engine, migrations_dir=migrations_dir)
        assert [migration.version for migration in executed] == ["0001", "0002"]

        with engine.begin() as conn:
            rows = conn.execute(text("SELECT id, name FROM widgets ORDER BY id")).fetchall()
            applied = conn.execute(
                text(f"SELECT version FROM {MIGRATIONS_TABLE} ORDER BY version")
            ).fetchall()

        assert rows == [(1, "alpha"), (2, "beta")]
        assert applied == [("0001",), ("0002",)]

        assert apply_schema_migrations(engine=engine, migrations_dir=migrations_dir) == []
    finally:
        engine.dispose()


def test_apply_schema_migrations_rolls_back_failed_migration(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_migration(
        migrations_dir,
        "0001_create_widgets.sql",
        """
        CREATE TABLE widgets (
            id INTEGER PRIMARY KEY
        );
        """,
    )
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'failure.db'}")
    try:
        assert [
            migration.version
            for migration in apply_schema_migrations(engine=engine, migrations_dir=migrations_dir)
        ] == ["0001"]

        _write_migration(
            migrations_dir,
            "0002_broken_migration.sql",
            """
            INSERT INTO widgets (id) VALUES (2);
            INSERT INTO missing_table(id) VALUES (1);
            """,
        )

        with pytest.raises(Exception):
            apply_schema_migrations(engine=engine, migrations_dir=migrations_dir)

        with engine.begin() as conn:
            applied = conn.execute(
                text(f"SELECT version FROM {MIGRATIONS_TABLE} ORDER BY version")
            ).fetchall()
            widgets_exists = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'widgets'"
                )
            ).fetchone()
            widget_rows = conn.execute(text("SELECT id FROM widgets ORDER BY id")).fetchall()

        assert applied == [("0001",)]
        assert widgets_exists is not None
        assert widget_rows == []
    finally:
        engine.dispose()


def test_apply_schema_migrations_adopts_existing_baseline_schema(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_migration(
        migrations_dir,
        "0001_baseline.sql",
        """
        CREATE TABLE widgets (
            id INTEGER PRIMARY KEY
        );
        """,
    )
    _write_migration(
        migrations_dir,
        "0002_seed_widgets.sql",
        """
        INSERT INTO widgets (id) VALUES (7);
        """,
    )

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'adopt.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE widgets (id INTEGER PRIMARY KEY)")

        executed = apply_schema_migrations(engine=engine, migrations_dir=migrations_dir)

        assert [migration.version for migration in executed] == ["0002"]

        with engine.begin() as conn:
            applied = conn.execute(
                text(f"SELECT version FROM {MIGRATIONS_TABLE} ORDER BY version")
            ).fetchall()
            widget_rows = conn.execute(text("SELECT id FROM widgets ORDER BY id")).fetchall()

        assert applied == [("0001",), ("0002",)]
        assert widget_rows == [(7,)]
    finally:
        engine.dispose()


def test_apply_schema_migrations_adopts_existing_schema_when_history_table_is_empty(
    tmp_path: Path,
) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_migration(
        migrations_dir,
        "0001_baseline.sql",
        """
        CREATE TABLE widgets (
            id INTEGER PRIMARY KEY
        );
        """,
    )

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'adopt-empty-history.db'}")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE widgets (id INTEGER PRIMARY KEY)")
            conn.exec_driver_sql(
                f"""
                CREATE TABLE {MIGRATIONS_TABLE} (
                    version TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL
                )
                """
            )

        assert apply_schema_migrations(engine=engine, migrations_dir=migrations_dir) == []

        with engine.begin() as conn:
            applied = conn.execute(
                text(f"SELECT version FROM {MIGRATIONS_TABLE} ORDER BY version")
            ).fetchall()

        assert applied == [("0001",)]
    finally:
        engine.dispose()


def test_recreate_scripts_use_versioned_migrations() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    recreate_source = (backend_dir / "scripts" / "database" / "recreate_db.py").read_text(
        encoding="utf-8"
    )
    migrate_source = (backend_dir / "scripts" / "database" / "migrate_db.py").read_text(
        encoding="utf-8"
    )

    assert "apply_schema_migrations" in recreate_source
    assert "apply_schema_migrations" in migrate_source
    assert "bootstrap_current_schema" not in recreate_source
