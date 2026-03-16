#!/usr/bin/env python3
"""
Drop and rebuild the development database through versioned migrations.

Use this during development when you want a fresh database with the current
authoritative schema, indexes, and built-in skills.
"""

from app.config.database import sync_engine, SessionLocal
from app.config.settings import settings
from app.database.migrations import apply_schema_migrations
from app.database.models import User
from app.chat.skills.store import upsert_builtin_skills_from_filesystem
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
import sys


def recreate_database(
    admin_email: Optional[str] = None,
    admin_name: Optional[str] = None,
    local_user_email: Optional[str] = None,
    local_user_name: Optional[str] = None,
    local_user_department: Optional[str] = None,
):
    """Drop all tables and recreate them with current schema"""
    try:
        # Clear connection pool to prevent blocking on DROP SCHEMA
        sync_engine.dispose()

        # Drop all tables - PostgreSQL: drop and recreate public schema
        with sync_engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()

        # Create schema objects through the canonical migration path.
        executed = apply_schema_migrations()
        if executed:
            print(
                "[recreate_db] schema migrated:",
                ", ".join(f"{migration.version}_{migration.name}" for migration in executed),
            )
        else:
            print("[recreate_db] schema already current.")

        seed_builtin_skills()

        # Optionally seed an initial admin user
        if admin_email:
            seed_admin_user(admin_email=admin_email, admin_name=admin_name)
        if local_user_email:
            seed_local_workspace_user(
                local_user_email=local_user_email,
                local_user_name=local_user_name,
                local_user_department=local_user_department,
            )

    except Exception as e:
        raise


def seed_builtin_skills():
    """Load built-in filesystem skills into DB skill tables."""
    db: Session = SessionLocal()
    try:
        stats = upsert_builtin_skills_from_filesystem(db)
        db.commit()
        print(
            "[recreate_db] seeded built-in skills:",
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


def seed_admin_user(admin_email: str, admin_name: Optional[str] = None):
    """Create or promote a user to admin by email.

    - If the user exists, updates role to 'admin' and keeps other fields.
    - If not, creates a new active user with role 'admin'.
    """
    admin_email = admin_email.strip().lower()
    admin_name = admin_name or admin_email.split("@")[0]
    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.email == admin_email).first()
        if user:
            user.role = "admin"
            user.user_tier = "power"
            db.commit()
        else:
            user = User(
                email=admin_email,
                name=admin_name,
                role="admin",
                user_tier="power",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    except IntegrityError as ie:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


def seed_local_workspace_user(
    local_user_email: str,
    local_user_name: Optional[str] = None,
    local_user_department: Optional[str] = None,
):
    """Create or normalize the singleton local workspace user."""
    local_user_email = local_user_email.strip().lower()
    if not local_user_email:
        return

    local_user_name = local_user_name or "assistant"
    local_user_department = local_user_department or "Local"

    db: Session = SessionLocal()
    try:
        user = db.query(User).filter(User.email == local_user_email).first()
        if user:
            user.role = "user"
            user.user_tier = "power"
            user.name = local_user_name
            user.department = local_user_department
            user.is_active = True
            db.commit()
        else:
            user = User(
                email=local_user_email,
                name=local_user_name,
                department=local_user_department,
                role="user",
                user_tier="power",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
    except IntegrityError as ie:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    # Optional CLI args: admin email and name
    admin_email = None
    admin_name = None
    if len(sys.argv) >= 2:
        admin_email = sys.argv[1]
    if len(sys.argv) >= 3:
        admin_name = sys.argv[2]

    if not admin_email:
        admin_email = "owner@example.com"
        admin_name = "Owner"

    recreate_database(
        admin_email=admin_email,
        admin_name=admin_name,
        local_user_email=(settings.local_user_email or "assistant@local").strip().lower(),
        local_user_name=(settings.local_user_name or "assistant").strip() or "assistant",
        local_user_department=(settings.local_user_department or "Local").strip() or "Local",
    )
