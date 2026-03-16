#!/usr/bin/env python3
"""
Script to run custom SQL queries against the database for analysis.
Usage:
    python query_db.py "SELECT * FROM users LIMIT 5"
    python query_db.py --file query.sql
    python query_db.py --thumbs-down  # Pre-built query for thumbs down feedback
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from sqlalchemy import text
from sqlalchemy.orm import Session
from app.config.database import sync_engine
from datetime import datetime
import argparse
from typing import Any, List, Dict


def format_value(value: Any) -> str:
    """Format a value for display"""
    if value is None:
        return "NULL"
    elif isinstance(value, datetime):
        return value.strftime('%Y-%m-%d %H:%M:%S')
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, str):
        # Truncate long strings
        if len(value) > 100:
            return value[:97] + "..."
        return value
    else:
        return str(value)


def print_table(columns: List[str], rows: List[tuple]):
    """Print results in a formatted table"""
    if not rows:
        print("📭 No results found")
        return

    # Calculate column widths
    col_widths = []
    for i, col in enumerate(columns):
        max_width = len(col)
        for row in rows:
            value_str = format_value(row[i])
            max_width = max(max_width, len(value_str))
        col_widths.append(min(max_width, 50))  # Cap at 50 chars

    # Print header
    header = " | ".join(col.ljust(col_widths[i]) for i, col in enumerate(columns))
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    # Print rows
    for row in rows:
        formatted_row = " | ".join(
            format_value(row[i]).ljust(col_widths[i])[:col_widths[i]]
            for i in range(len(columns))
        )
        print(formatted_row)

    print("=" * len(header))
    print(f"📊 Total rows: {len(rows)}")


def execute_query(query: str, show_sql: bool = True):
    """Execute a SQL query and display results"""

    if show_sql:
        print("🔍 Executing query:")
        print("-" * 80)
        print(query)
        print("-" * 80)
        print()

    with Session(sync_engine) as db:
        try:
            result = db.execute(text(query))

            # Check if this is a SELECT query
            if result.returns_rows:
                rows = result.fetchall()
                columns = list(result.keys())
                print_table(columns, rows)
            else:
                # For INSERT, UPDATE, DELETE, etc.
                db.commit()
                print(f"✅ Query executed successfully. Rows affected: {result.rowcount}")

        except Exception as e:
            print(f"❌ Query failed: {str(e)}")
            return False

    return True


def get_thumbs_down_query() -> str:
    """Get the pre-built query for thumbs down feedback analysis"""
    return """
SELECT
    ef.id as feedback_id,
    u.email as user_email,
    u.name as user_name,
    c.id as conversation_id,
    c.title as conversation_title,
    m_assistant.id as assistant_message_id,
    m_assistant.model_provider as model_provider,
    m_assistant.model_name as model_name,
    m_assistant.text as assistant_text,
    m_assistant.created_at as assistant_message_time,
    m_user.text as user_text,
    m_user.created_at as user_message_time,
    ef.issue_description,
    ef.time_spent_minutes,
    ef.created_at as feedback_time
FROM message_feedbacks ef
JOIN users u ON ef.user_id = u.id
JOIN messages m_assistant ON ef.message_id = m_assistant.id
JOIN conversations c ON m_assistant.conversation_id = c.id
LEFT JOIN LATERAL (
    SELECT text, created_at
    FROM messages
    WHERE conversation_id = m_assistant.conversation_id
      AND role = 'user'
      AND (
        created_at < m_assistant.created_at
        OR (created_at = m_assistant.created_at AND id < m_assistant.id)
      )
    ORDER BY created_at DESC, id DESC
    LIMIT 1
) m_user ON TRUE
WHERE ef.rating = 'down'
ORDER BY ef.created_at DESC;
"""


def main():
    parser = argparse.ArgumentParser(
        description="Run custom SQL queries against the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a simple query
  python query_db.py "SELECT email, name FROM users LIMIT 5"

  # Run a query from a file
  python query_db.py --file my_query.sql

  # Use pre-built thumbs down analysis
  python query_db.py --thumbs-down

  # Run without showing SQL
  python query_db.py --no-show-sql "SELECT COUNT(*) FROM users"
        """
    )

    parser.add_argument(
        'query',
        nargs='?',
        help='SQL query to execute'
    )
    parser.add_argument(
        '--file', '-f',
        help='Read query from file'
    )
    parser.add_argument(
        '--thumbs-down',
        action='store_true',
        help='Run pre-built query for thumbs down feedback analysis'
    )
    parser.add_argument(
        '--no-show-sql',
        action='store_true',
        help='Do not display the SQL query before execution'
    )

    args = parser.parse_args()

    # Determine which query to run
    query = None

    if args.thumbs_down:
        query = get_thumbs_down_query()
        print("📊 Running thumbs down feedback analysis...")
        print()
    elif args.file:
        try:
            with open(args.file, 'r') as f:
                query = f.read()
        except FileNotFoundError:
            print(f"❌ File not found: {args.file}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error reading file: {str(e)}")
            sys.exit(1)
    elif args.query:
        query = args.query
    else:
        parser.print_help()
        sys.exit(1)

    # Execute the query
    success = execute_query(query, show_sql=not args.no_show_sql)

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
