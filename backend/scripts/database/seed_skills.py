#!/usr/bin/env python3
"""
Seed or update built-in skills in the database from the filesystem.

Does not touch any other data. Safe to run at any time.

Usage:
    cd backend && PYTHONPATH=. python scripts/database/seed_skills.py
"""

from app.config.database import SessionLocal
from app.database import models  # noqa: F401 — register all models
from app.chat.skills.store import upsert_builtin_skills_from_filesystem
from sqlalchemy.orm import Session


def seed_skills():
    """Upsert built-in skills from filesystem into the database."""
    db: Session = SessionLocal()
    try:
        stats = upsert_builtin_skills_from_filesystem(db)
        db.commit()
        print(
            "[seed_skills] Done:",
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
    seed_skills()
