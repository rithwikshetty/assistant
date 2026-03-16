"""Admin-only database query tools for database analysis and reporting."""

import logging
from typing import Any, Dict, List
import re
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

from ...logging import log_event

logger = logging.getLogger(__name__)


def get_database_schema(db: Session, table_name: str = None) -> Dict[str, Any]:
    """Get database schema information.

    Args:
        db: Database session
        table_name: Optional specific table name to get schema for

    Returns:
        Dictionary containing schema information
    """
    try:
        inspector = inspect(db.bind)
        base_table_names = inspector.get_table_names()

        if table_name:
            # Get schema for specific table
            if table_name not in base_table_names:
                return {
                    "error": f"Table '{table_name}' not found",
                    "available_tables": base_table_names,
                }

            columns = inspector.get_columns(table_name)
            indexes = inspector.get_indexes(table_name)
            foreign_keys = inspector.get_foreign_keys(table_name)

            return {
                "table": table_name,
                "columns": [
                    {
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col["nullable"],
                        "default": str(col.get("default")) if col.get("default") else None,
                        "primary_key": col.get("primary_key", False),
                    }
                    for col in columns
                ],
                "indexes": [
                    {
                        "name": idx["name"],
                        "columns": idx["column_names"],
                        "unique": idx["unique"],
                    }
                    for idx in indexes
                ],
                "foreign_keys": [
                    {
                        "name": fk.get("name"),
                        "columns": fk["constrained_columns"],
                        "referred_table": fk["referred_table"],
                        "referred_columns": fk["referred_columns"],
                    }
                    for fk in foreign_keys
                ],
            }

        # Get schema for all tables
        all_tables = list(base_table_names)
        # Fallback: try public schema explicitly
        if not all_tables:
            for schema_name in ("public",):
                try:
                    names = inspector.get_table_names(schema=schema_name)
                    if names:
                        # Prepend schema for clarity
                        all_tables = [f"{schema_name}.{n}" for n in names]
                        break
                except Exception:
                    continue

        table_info = []

        def coerce_simple_type(col_type: Any) -> str:
            try:
                return str(col_type)
            except Exception:
                return ""

        if all_tables:
            for tbl in all_tables:
                # If table is schema-qualified, split for inspector column lookup
                schema_for_cols = None
                tbl_name = tbl
                if "." in tbl:
                    schema_for_cols, tbl_name = tbl.split(".", 1)
                try:
                    columns = inspector.get_columns(tbl_name, schema=schema_for_cols)
                except Exception:
                    columns = []
                table_info.append({
                    "table_name": tbl,
                    "column_count": len(columns),
                    "columns": [
                        {
                            "name": col.get("name"),
                            "type": coerce_simple_type(col.get("type")),
                            "nullable": bool(col.get("nullable")),
                            "primary_key": bool(col.get("primary_key", False)),
                        }
                        for col in columns
                    ],
                })
        else:
            # Last-resort: PostgreSQL catalogs (faster/more complete than information_schema)
            try:
                rows = db.execute(text("""
                    SELECT n.nspname AS table_schema, c.relname AS table_name
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind IN ('r', 'p')
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY n.nspname, c.relname
                """)).fetchall()
                all_tables = [f"{r[0]}.{r[1]}" for r in rows]

                catalog_columns = db.execute(text("""
                    SELECT
                        n.nspname AS table_schema,
                        c.relname AS table_name,
                        a.attname AS column_name,
                        pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                        (NOT a.attnotnull) AS is_nullable
                    FROM pg_catalog.pg_attribute a
                    JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind IN ('r', 'p')
                      AND n.nspname NOT IN ('pg_catalog', 'information_schema')
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                    ORDER BY n.nspname, c.relname, a.attnum
                """)).fetchall()

                columns_by_table: Dict[str, List[Dict[str, Any]]] = {}
                for schema_name, table_name_value, column_name, data_type, is_nullable in catalog_columns:
                    key = f"{schema_name}.{table_name_value}"
                    columns_by_table.setdefault(key, []).append(
                        {
                            "name": column_name,
                            "type": str(data_type),
                            "nullable": bool(is_nullable),
                            "primary_key": False,
                        }
                    )

                for schema_name, table in [(r[0], r[1]) for r in rows]:
                    table_key = f"{schema_name}.{table}"
                    table_columns = columns_by_table.get(table_key, [])
                    table_info.append({
                        "table_name": table_key,
                        "column_count": len(table_columns),
                        "columns": table_columns,
                    })
            except Exception:
                # Still nothing; return empty result with hint
                return {
                    "database_type": "PostgreSQL",
                    "table_count": 0,
                    "tables": [],
                    "note": "No tables visible via inspector. Check DB permissions or connection.",
                }

        return {
            "database_type": "PostgreSQL",
            "table_count": len(all_tables),
            "tables": table_info,
            "note": "Use PostgreSQL syntax: LIMIT/OFFSET, ILIKE, JSONB operators (->, ->>), LATERAL, DISTINCT ON.",
        }

    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "admin.db.schema_fetch_failed",
            "error",
            exc_info=exc,
        )
        return {
            "error": f"Failed to retrieve schema: {str(exc)}",
        }


def _ensure_schema_cached(context: Dict[str, Any], db: Session) -> Dict[str, List[str]]:
    """Load and cache a minimal schema lookup map {table_name: [columns...]}.

    Also marks context['db_schema_checked'] = True to satisfy the "check schema at least once"
    requirement before running arbitrary queries.
    """
    if context.get("db_schema_cache") and isinstance(context["db_schema_cache"], dict):
        context["db_schema_checked"] = True
        return context["db_schema_cache"]  # type: ignore[return-value]

    lookup: Dict[str, List[str]] = {}
    try:
        inspector = inspect(db.bind)
        for tbl in inspector.get_table_names():
            cols = [c["name"] for c in inspector.get_columns(tbl)]
            lookup[tbl] = cols
        context["db_schema_cache"] = lookup
        context["db_schema_checked"] = True
        return lookup
    except Exception:
        # Don’t block queries if inspector fails; just leave empty.
        context["db_schema_checked"] = True
        return {}


def _normalize_identifier_token(token: str) -> str:
    normalized = (token or "").strip().strip("[]").strip('"')
    if "." in normalized:
        normalized = normalized.rsplit(".", 1)[-1].strip("[]").strip('"')
    return normalized


def _extract_aliases(sql: str) -> Dict[str, str]:
    """Very light alias extractor: maps alias -> table for FROM/JOIN clauses."""
    alias_map: Dict[str, str] = {}
    # Normalize spacing
    s = " " + re.sub(r"\s+", " ", sql) + " "
    # FROM table [AS] alias
    for m in re.finditer(r"\bFROM\s+([\w\.\[\]\"]+)\s+(?:AS\s+)?([\w\[\]\"]+)\b", s, re.IGNORECASE):
        table = _normalize_identifier_token(m.group(1))
        alias = _normalize_identifier_token(m.group(2))
        alias_map[alias] = table
    # JOIN table [AS] alias
    for m in re.finditer(r"\bJOIN\s+([\w\.\[\]\"]+)\s+(?:AS\s+)?([\w\[\]\"]+)\b", s, re.IGNORECASE):
        table = _normalize_identifier_token(m.group(1))
        alias = _normalize_identifier_token(m.group(2))
        alias_map[alias] = table
    # Also map direct table references as their own alias if used without alias
    for m in re.finditer(r"\bFROM\s+([\w\.\[\]\"]+)\b", s, re.IGNORECASE):
        table = _normalize_identifier_token(m.group(1))
        alias_map.setdefault(table, table)
    return alias_map


def _strip_leading_comments(query: str) -> str:
    """Remove leading SQL comments and whitespace so validation sees the first statement.

    Handles -- line comments and /* block comments */ at the start.
    """
    s = query or ""
    i = 0
    n = len(s)
    while True:
        # skip whitespace
        while i < n and s[i].isspace():
            i += 1
        # line comment
        if i + 1 < n and s[i] == '-' and s[i + 1] == '-':
            i += 2
            while i < n and s[i] not in ('\n', '\r'):
                i += 1
            continue
        # block comment
        if i + 1 < n and s[i] == '/' and s[i + 1] == '*':
            i += 2
            while i + 1 < n and not (s[i] == '*' and s[i + 1] == '/'):
                i += 1
            i = i + 2 if i + 1 < n else n
            continue
        break
    return s[i:]


def _fix_invalid_alias_columns(query: str, alias_map: Dict[str, str], schema: Dict[str, List[str]]) -> tuple[str, List[str]]:
    """If an alias.column refers to a non-existent column, attempt safe fixes.

    Current safe fix: when table == 'conversations' and column == 'conversation_id', rewrite to alias.id
    (the primary key). Similar pattern for other obvious self-referential mistakes.
    """
    suggestions: List[str] = []

    def repl(m: re.Match[str]) -> str:
        full = m.group(0)
        alias = m.group(1)
        col = m.group(2)
        table = alias_map.get(alias)
        if not table:
            return full
        cols = set(schema.get(table, []))
        if col in cols:
            return full
        # Heuristic: conversations.conversation_id -> conversations.id
        if table == "conversations" and col == "conversation_id" and "id" in cols:
            suggestions.append(f"Rewrote {alias}.conversation_id -> {alias}.id")
            return f"{alias}.id"
        # Similar: projects.project_id -> projects.id; users.user_id -> users.id
        if col == f"{table[:-1]}_id" and "id" in cols:  # crude singularization
            suggestions.append(f"Rewrote {alias}.{col} -> {alias}.id")
            return f"{alias}.id"
        return full

    new_q = re.sub(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b", repl, query)
    return new_q, suggestions


def _analyze_hints(query: str) -> List[str]:
    hints: List[str] = []
    q = query or ""
    if re.search(r"\bJSON_EXTRACT\s*\(", q, re.IGNORECASE):
        hints.append("MySQL JSON_EXTRACT(...) detected. Prefer PostgreSQL JSONB operators like ->, ->>, and #>>.")
    if re.search(r"\bDATE_FORMAT\s*\(", q, re.IGNORECASE):
        hints.append("MySQL DATE_FORMAT(...) detected. Use PostgreSQL to_char(timestamp, format).")
    if re.search(r"\bSTR_TO_DATE\s*\(", q, re.IGNORECASE):
        hints.append("MySQL STR_TO_DATE(...) detected. Use PostgreSQL to_timestamp(text, format).")
    if re.search(r"\bREGEXP\b", q, re.IGNORECASE):
        hints.append("MySQL REGEXP detected. Use PostgreSQL regex operators (~, ~*, !~, !~*).")
    if re.search(r"\bLOWER\s*\([^)]*\)\s+LIKE\b", q, re.IGNORECASE):
        hints.append("Consider PostgreSQL ILIKE for case-insensitive matching instead of LOWER(column) LIKE ...")
    return hints


def _apply_postgres_rewrites(query: str) -> tuple[str, List[str]]:
    """Apply conservative rewrites for common MySQL syntax into PostgreSQL syntax."""
    rewritten = query
    rewrites: List[str] = []

    def limit_repl(m: re.Match[str]) -> str:
        offset = m.group(1)
        limit = m.group(2)
        rewrites.append(f"Rewrote LIMIT {offset},{limit} -> LIMIT {limit} OFFSET {offset}")
        return f"LIMIT {limit} OFFSET {offset}"

    rewritten = re.sub(r"\bLIMIT\s+(\d+)\s*,\s*(\d+)\b", limit_repl, rewritten, flags=re.IGNORECASE)

    if re.search(r"`[^`]+`", rewritten):
        rewritten = re.sub(r"`([^`]+)`", r'"\1"', rewritten)
        rewrites.append("Replaced MySQL backtick identifiers with PostgreSQL double-quoted identifiers.")

    if re.search(r"\bIFNULL\s*\(", rewritten, re.IGNORECASE):
        rewritten = re.sub(r"\bIFNULL\s*\(", "COALESCE(", rewritten, flags=re.IGNORECASE)
        rewrites.append("Replaced MySQL IFNULL(...) with PostgreSQL COALESCE(...).")

    return rewritten, rewrites


def _preflight_sql(query: str, context: Dict[str, Any], db: Session) -> tuple[str, Dict[str, Any]]:
    """Run schema check and apply conservative rewrites; return modified query and debug info."""
    schema = _ensure_schema_cached(context, db)
    alias_map = _extract_aliases(query)
    # Normalize leading comments
    stripped = _strip_leading_comments(query)
    q1, alias_fixes = _fix_invalid_alias_columns(stripped, alias_map, schema)
    q2, syntax_rewrites = _apply_postgres_rewrites(q1)
    info: Dict[str, Any] = {}
    if alias_fixes:
        info["column_fixes"] = alias_fixes
    if syntax_rewrites:
        info["syntax_rewrites"] = syntax_rewrites
    hints = _analyze_hints(q2)
    if hints:
        info["hints"] = hints
    return q2, info


def execute_database_query(db: Session, query: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a SQL query against the database.

    Args:
        db: Database session
        query: SQL query to execute

    Returns:
        Dictionary containing query results or error
    """
    # Security check: only allow SELECT queries
    # Allow leading comments before SELECT/WITH
    query_sans_comments = _strip_leading_comments(query)
    query_stripped = query_sans_comments.strip().upper()
    if not query_stripped.startswith("SELECT") and not query_stripped.startswith("WITH"):
        return {
            "error": "Only SELECT queries are allowed. For data modifications, use database scripts directly.",
            "query": query,
        }

    # Additional security: block dangerous SQL commands (using word boundaries to avoid false positives with column names)
    # This prevents "DROP TABLE" but allows "created_at" or "updated_at"
    dangerous_patterns = [
        r'\bDROP\s+',      # DROP TABLE, DROP INDEX, etc.
        r'\bDELETE\s+',    # DELETE FROM
        r'\bINSERT\s+',    # INSERT INTO
        r'\bUPDATE\s+',    # UPDATE table
        r'\bALTER\s+',     # ALTER TABLE
        r'\bCREATE\s+',    # CREATE TABLE (but not created_at)
        r'\bTRUNCATE\s+',  # TRUNCATE TABLE
        r'\bEXEC\s*\(',    # EXEC(...)
        r'\bEXECUTE\s*\(', # EXECUTE(...)
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, query_stripped):
            keyword = pattern.replace(r'\b', '').replace(r'\s+', '').replace(r'\s*\(', '')
            return {
                "error": f"Query contains forbidden SQL command: {keyword}. Only SELECT queries are allowed.",
                "query": query,
            }

    # Preflight: ensure schema checked and apply conservative SQL
    preflight_query, preflight_info = _preflight_sql(query, context, db)

    try:
        result = db.execute(text(preflight_query))

        if result.returns_rows:
            rows = result.fetchall()
            columns = list(result.keys())

            # Format results
            formatted_rows = []
            for row in rows:
                formatted_row = {}
                for i, col in enumerate(columns):
                    value = row[i]
                    # Handle different types
                    if value is None:
                        formatted_row[col] = None
                    elif hasattr(value, 'isoformat'):  # datetime objects
                        formatted_row[col] = value.isoformat()
                    else:
                        formatted_row[col] = str(value) if not isinstance(value, (int, float, bool)) else value
                formatted_rows.append(formatted_row)

            payload = {
                "success": True,
                "row_count": len(rows),
                "columns": columns,
                "rows": formatted_rows[:100],  # Limit to 100 rows for safety
                "truncated": len(rows) > 100,
                "note": f"Showing {min(len(rows), 100)} of {len(rows)} rows" if len(rows) > 100 else None,
            }
            if preflight_info:
                payload["preflight"] = preflight_info
            return payload
        else:
            # For read-only SELECT/CTE queries that produce no rowset (rare),
            # surface a successful 0-row result instead of an error.
            return {
                "success": True,
                "row_count": 0,
                "columns": [],
                "rows": [],
                "truncated": False,
                "note": "Query returned 0 rows",
                "query": preflight_query,
                **({"preflight": preflight_info} if preflight_info else {}),
            }

    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "admin.db.query_failed",
            "error",
            exc_info=exc,
        )
        error_payload: Dict[str, Any] = {
            "error": f"Query execution failed: {str(exc)}",
            "query": preflight_query,
            "hint": "Check PostgreSQL syntax: LIMIT/OFFSET, ILIKE, JSONB operators, LATERAL, INTERVAL.",
        }
        # Offer suggested changes if preflight made edits
        if preflight_info:
            error_payload["preflight"] = preflight_info
        return error_payload


async def execute_admin_get_database_schema(
    arguments: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute admin_get_database_schema tool."""
    db = context.get("db")
    if not db:
        raise RuntimeError("Database session not available in context")
    # Admin-only runtime guard
    if not bool(context.get("is_admin")):
        return {"error": "Admin access required. This tool is restricted to administrators only."}

    table_name = arguments.get("table_name")
    if table_name:
        table_name = table_name.strip()
    result = get_database_schema(db, table_name)
    # Cache a lightweight schema map for later validation
    try:
        _ensure_schema_cached(context, db)
    except Exception:
        pass
    return result


async def execute_admin_query_database(
    arguments: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute admin_query_database tool."""
    db = context.get("db")
    if not db:
        raise RuntimeError("Database session not available in context")
    # Admin-only runtime guard
    if not bool(context.get("is_admin")):
        return {"error": "Admin access required. This tool is restricted to administrators only."}

    query = arguments.get("query")
    if not query or not isinstance(query, str):
        raise ValueError("Query parameter is required and must be a string")

    query = query.strip()
    if not query:
        raise ValueError("Query cannot be empty")

    # Ensure schema is checked at least once per stream before any query runs
    try:
        _ensure_schema_cached(context, db)
    except Exception:
        # Non-fatal; continue
        pass

    return execute_database_query(db, query, context)
