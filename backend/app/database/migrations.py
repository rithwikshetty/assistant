from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import List

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.engine import Engine

from ..config.database import sync_engine


MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "database" / "migrations"
MIGRATIONS_TABLE = "schema_migrations"


@dataclass(frozen=True)
class MigrationFile:
    version: str
    name: str
    path: Path


def list_migration_files(migrations_dir: Path = MIGRATIONS_DIR) -> List[MigrationFile]:
    parsed_files: List[tuple[int, MigrationFile]] = []
    seen_versions: set[int] = set()

    for path in migrations_dir.glob("*.sql"):
        stem = path.stem
        if "_" not in stem:
            raise ValueError(f"Invalid migration filename: {path.name}")
        version, name = stem.split("_", 1)
        if not version.isdigit():
            raise ValueError(f"Invalid migration version in {path.name}")
        version_number = int(version)
        if version_number in seen_versions:
            raise ValueError(f"Duplicate migration version {version}")
        seen_versions.add(version_number)
        parsed_files.append(
            (
                version_number,
                MigrationFile(version=version, name=name, path=path),
            )
        )

    parsed_files.sort(key=lambda item: item[0])
    return [migration for _, migration in parsed_files]


def ensure_migrations_table(engine: Engine = sync_engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} (
                    version TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL
                )
                """
            )
        )


def _has_migrations_table(engine: Engine = sync_engine) -> bool:
    return inspect(engine).has_table(MIGRATIONS_TABLE)


def _list_non_migration_tables(engine: Engine = sync_engine) -> set[str]:
    return {
        table_name
        for table_name in inspect(engine).get_table_names()
        if table_name != MIGRATIONS_TABLE
    }


def _get_migration_row_count(engine: Engine = sync_engine) -> int:
    if not _has_migrations_table(engine):
        return 0
    with engine.begin() as conn:
        return int(
            conn.execute(text(f"SELECT COUNT(*) FROM {MIGRATIONS_TABLE}")).scalar_one()
        )


def get_applied_migration_versions(engine: Engine = sync_engine) -> set[str]:
    ensure_migrations_table(engine)
    with engine.begin() as conn:
        rows = conn.execute(text(f"SELECT version FROM {MIGRATIONS_TABLE}")).fetchall()
    return {str(row[0]) for row in rows}


_DOLLAR_QUOTE_PATTERN = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def _statement_has_executable_sql(statement: str) -> bool:
    without_block_comments = re.sub(r"/\*.*?\*/", "", statement, flags=re.DOTALL)
    content_lines = [
        line for line in without_block_comments.splitlines()
        if not line.lstrip().startswith("--")
    ]
    return bool("".join(content_lines).strip())


def _split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    in_block_comment = False
    dollar_quote_tag: str | None = None
    index = 0
    text_length = len(sql_text)

    while index < text_length:
        if in_line_comment:
            char = sql_text[index]
            buffer.append(char)
            index += 1
            if char == "\n":
                in_line_comment = False
            continue

        if in_block_comment:
            if sql_text.startswith("*/", index):
                buffer.append("*/")
                index += 2
                in_block_comment = False
            else:
                buffer.append(sql_text[index])
                index += 1
            continue

        if dollar_quote_tag is not None:
            if sql_text.startswith(dollar_quote_tag, index):
                buffer.append(dollar_quote_tag)
                index += len(dollar_quote_tag)
                dollar_quote_tag = None
            else:
                buffer.append(sql_text[index])
                index += 1
            continue

        char = sql_text[index]
        next_two = sql_text[index:index + 2]

        if in_single_quote:
            buffer.append(char)
            index += 1
            if char == "'" and sql_text[index:index + 1] == "'":
                buffer.append("'")
                index += 1
            elif char == "'":
                in_single_quote = False
            continue

        if in_double_quote:
            buffer.append(char)
            index += 1
            if char == '"' and sql_text[index:index + 1] == '"':
                buffer.append('"')
                index += 1
            elif char == '"':
                in_double_quote = False
            continue

        if next_two == "--":
            buffer.append(next_two)
            index += 2
            in_line_comment = True
            continue

        if next_two == "/*":
            buffer.append(next_two)
            index += 2
            in_block_comment = True
            continue

        if char == "'":
            buffer.append(char)
            index += 1
            in_single_quote = True
            continue

        if char == '"':
            buffer.append(char)
            index += 1
            in_double_quote = True
            continue

        if char == "$":
            match = _DOLLAR_QUOTE_PATTERN.match(sql_text, index)
            if match:
                tag = match.group(0)
                buffer.append(tag)
                index += len(tag)
                dollar_quote_tag = tag
                continue

        if char == ";":
            statement = "".join(buffer).strip()
            if statement and _statement_has_executable_sql(statement):
                statements.append(statement)
            buffer.clear()
            index += 1
            continue

        buffer.append(char)
        index += 1

    statement = "".join(buffer).strip()
    if statement and _statement_has_executable_sql(statement):
        statements.append(statement)

    return statements


def _execute_sql_script(conn: Connection, sql_text: str) -> None:
    for statement in _split_sql_statements(sql_text):
        conn.exec_driver_sql(statement)


def _adopt_existing_schema_if_needed(
    *,
    engine: Engine,
    migration_files: list[MigrationFile],
) -> None:
    migration_row_count = _get_migration_row_count(engine)
    if migration_row_count > 0:
        return

    existing_tables = _list_non_migration_tables(engine)
    if not existing_tables:
        return

    if not migration_files:
        raise RuntimeError(
            "Existing schema found but no migration files are available to adopt it."
        )

    baseline_migration = migration_files[0]
    if "baseline" not in baseline_migration.name:
        raise RuntimeError(
            "Existing schema found without migration history, but the earliest migration "
            f"{baseline_migration.version}_{baseline_migration.name} is not a baseline."
        )

    ensure_migrations_table(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {MIGRATIONS_TABLE} (version, name, applied_at)
                VALUES (:version, :name, :applied_at)
                """
            ),
            {
                "version": baseline_migration.version,
                "name": baseline_migration.name,
                "applied_at": datetime.now(timezone.utc),
            },
        )


def apply_schema_migrations(
    *,
    engine: Engine = sync_engine,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> List[MigrationFile]:
    migration_files = list_migration_files(migrations_dir)
    _adopt_existing_schema_if_needed(engine=engine, migration_files=migration_files)
    ensure_migrations_table(engine)
    applied_versions = get_applied_migration_versions(engine)
    executed: List[MigrationFile] = []

    for migration in migration_files:
        if migration.version in applied_versions:
            continue
        sql_text = migration.path.read_text(encoding="utf-8")
        with engine.begin() as conn:
            _execute_sql_script(conn, sql_text)
            conn.execute(
                text(
                    f"""
                    INSERT INTO {MIGRATIONS_TABLE} (version, name, applied_at)
                    VALUES (:version, :name, :applied_at)
                    """
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": datetime.now(timezone.utc),
                },
            )
        executed.append(migration)

    return executed


def latest_migration_version(migrations_dir: Path = MIGRATIONS_DIR) -> str | None:
    migration_files = list_migration_files(migrations_dir)
    if not migration_files:
        return None
    return migration_files[-1].version
