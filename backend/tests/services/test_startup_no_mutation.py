"""LAT-006: Verify app startup does not mutate schema or seed data.

Startup must only verify connectivity and that skills are already
seeded — it must NOT call create_tables() or ensure_builtin_skills_seeded().
"""

from __future__ import annotations


def test_main_does_not_import_create_tables() -> None:
    """main.py must not import create_tables from database."""
    import app.main as main_module
    import inspect

    source = inspect.getsource(main_module)

    assert "create_tables" not in source, (
        "LAT-006: main.py must not import or call create_tables(). "
        "Schema creation belongs in migration scripts, not app startup."
    )


def test_main_does_not_import_ensure_builtin_skills_seeded() -> None:
    """main.py must not import ensure_builtin_skills_seeded."""
    import app.main as main_module
    import inspect

    source = inspect.getsource(main_module)

    assert "ensure_builtin_skills_seeded" not in source, (
        "LAT-006: main.py must not import or call ensure_builtin_skills_seeded(). "
        "Skill seeding belongs in seed_skills.py, not app startup."
    )


def test_main_startup_uses_readonly_skill_check() -> None:
    """main.py should verify skills exist with a read-only count query."""
    import app.main as main_module
    import inspect

    source = inspect.getsource(main_module)

    # Should use a SELECT count, not an upsert/insert
    assert "skills_verified" in source or "skills_missing" in source, (
        "LAT-006: main.py should verify skills with a read-only check, "
        "logging 'skills_verified' or 'skills_missing'."
    )


def test_main_startup_uses_readonly_db_check() -> None:
    """main.py should verify DB connectivity with SELECT 1, not create_all."""
    import app.main as main_module
    import inspect

    source = inspect.getsource(main_module)

    assert "SELECT 1" in source, (
        "LAT-006: main.py should verify DB connectivity with 'SELECT 1', "
        "not Base.metadata.create_all()."
    )
