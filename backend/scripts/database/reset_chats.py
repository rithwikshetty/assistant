#!/usr/bin/env python3
"""
Reset chat data while preserving users and tasks.

Use this during development to clear conversations, files, and analytics
while keeping users and their tasks intact.

Usage:
    cd backend && PYTHONPATH=. python scripts/database/reset_chats.py
"""

from app.config.database import sync_engine, SessionLocal
from app.database import models  # noqa: F401 — register all models
from app.chat.skills.store import upsert_builtin_skills_from_filesystem
from sqlalchemy import text
from sqlalchemy.orm import Session


# Tables that survive the reset
PRESERVED_TABLES = {
    "users",
    "tasks",
    "task_comments",
    "task_assignments",
    "user_preferences",
    "app_settings",
    "user_redaction_entries",
}


def reset_chats():
    """Clear all chat/file/analytics data while preserving users and tasks."""
    try:
        with sync_engine.connect() as conn:
            # Discover all tables in public schema
            result = conn.execute(text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ))
            all_tables = {row[0] for row in result}
            tables_to_clear = sorted(all_tables - PRESERVED_TABLES)

            if not tables_to_clear:
                print("[reset_chats] No tables to clear.")
                return

            preserved_found = sorted(PRESERVED_TABLES & all_tables)
            print(f"[reset_chats] Preserving {len(preserved_found)} tables: {preserved_found}")
            print(f"[reset_chats] Clearing {len(tables_to_clear)} tables: {tables_to_clear}")

            # 1. Null out task → conversation FK (preserved table references a cleared table)
            conn.execute(text(
                "UPDATE tasks SET conversation_id = NULL "
                "WHERE conversation_id IS NOT NULL"
            ))

            # 2. Temporarily drop the FK so TRUNCATE CASCADE won't cascade into tasks
            conn.execute(text(
                "ALTER TABLE tasks "
                "DROP CONSTRAINT IF EXISTS tasks_conversation_id_fkey"
            ))

            # 3. Truncate all non-preserved tables in one statement
            table_list = ", ".join(f'"{t}"' for t in tables_to_clear)
            conn.execute(text(f"TRUNCATE {table_list} CASCADE"))

            # 4. Re-add the FK constraint
            conn.execute(text(
                "ALTER TABLE tasks ADD CONSTRAINT tasks_conversation_id_fkey "
                "FOREIGN KEY (conversation_id) REFERENCES conversations(id)"
            ))

            conn.commit()

        # 5. Re-seed built-in skills (skills table was cleared)
        _seed_builtin_skills()

        print("[reset_chats] Done. Users and tasks preserved, chat data cleared.")

    except Exception:
        raise


def _seed_builtin_skills():
    """Load built-in filesystem skills into DB skill tables."""
    db: Session = SessionLocal()
    try:
        stats = upsert_builtin_skills_from_filesystem(db)
        db.commit()
        print(
            "[reset_chats] seeded built-in skills:",
            f"discovered={stats['skills_discovered']}",
            f"inserted={stats['skills_inserted']}",
            f"updated={stats['skills_updated']}",
            f"deleted={stats['skills_deleted']}",
            f"files={stats['files_written']}",
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    reset_chats()
