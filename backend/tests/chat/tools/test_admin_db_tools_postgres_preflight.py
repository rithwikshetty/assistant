from app.chat.tools.admin_db_tools import (
    _analyze_hints,
    _apply_postgres_rewrites,
    _extract_aliases,
)


def test_apply_postgres_rewrites_converts_mysql_limit_ifnull_and_backticks() -> None:
    query = "SELECT IFNULL(`u`.`name`, '') FROM `users` u LIMIT 5, 10"

    rewritten, rewrites = _apply_postgres_rewrites(query)

    assert "COALESCE(" in rewritten
    assert "LIMIT 10 OFFSET 5" in rewritten
    assert "`" not in rewritten
    assert "IFNULL(" not in rewritten
    assert any("LIMIT 5,10" in entry or "LIMIT 5, 10" in entry for entry in rewrites)
    assert any("backtick" in entry.lower() for entry in rewrites)
    assert any("IFNULL" in entry for entry in rewrites)


def test_analyze_hints_flags_mysql_specific_constructs() -> None:
    query = (
        "SELECT JSON_EXTRACT(payload, '$.a'), "
        "DATE_FORMAT(created_at, '%Y-%m-%d'), "
        "STR_TO_DATE('2024-01-01', '%Y-%m-%d') "
        "FROM events WHERE name REGEXP 'test' "
        "AND LOWER(name) LIKE '%foo%'"
    )

    hints = _analyze_hints(query)

    assert any("JSON_EXTRACT" in hint for hint in hints)
    assert any("DATE_FORMAT" in hint for hint in hints)
    assert any("STR_TO_DATE" in hint for hint in hints)
    assert any("REGEXP" in hint for hint in hints)
    assert any("ILIKE" in hint for hint in hints)


def test_extract_aliases_normalizes_schema_qualified_names() -> None:
    query = (
        "SELECT * FROM public.messages AS m "
        "JOIN \"public\".\"users\" u ON u.id = m.user_id"
    )

    alias_map = _extract_aliases(query)

    assert alias_map.get("m") == "messages"
    assert alias_map.get("u") == "users"
