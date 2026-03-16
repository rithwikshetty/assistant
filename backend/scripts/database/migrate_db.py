#!/usr/bin/env python3
from __future__ import annotations

from app.database.migrations import apply_schema_migrations


def main() -> None:
    executed = apply_schema_migrations()
    if executed:
        for migration in executed:
            print(f"[migrate_db] applied {migration.version}_{migration.name}")
    else:
        print("[migrate_db] no pending migrations")


if __name__ == "__main__":
    main()
