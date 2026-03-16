#!/usr/bin/env python3
"""Rebuild admin analytics rollup tables from canonical runtime tables."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.config.database import sync_engine


def rebuild_rollups() -> None:
    with sync_engine.begin() as conn:
        # Rebuild per-user snapshot for users admin table.
        conn.execute(text("DELETE FROM admin_user_rollup"))
        conn.execute(
            text(
                """
                INSERT INTO admin_user_rollup (
                    user_id,
                    conversation_count,
                    assistant_turn_count,
                    total_cost_usd,
                    last_assistant_turn_at
                )
                SELECT
                    u.id AS user_id,
                    COALESCE(c.conversation_count, 0) AS conversation_count,
                    COALESCE(t.assistant_turn_count, 0) AS assistant_turn_count,
                    COALESCE(t.total_cost_usd, 0) AS total_cost_usd,
                    t.last_assistant_turn_at
                FROM users u
                LEFT JOIN (
                    SELECT
                        conversations.user_id AS user_id,
                        COUNT(conversations.id) AS conversation_count
                    FROM conversations
                    GROUP BY conversations.user_id
                ) c ON c.user_id = u.id
                LEFT JOIN (
                    SELECT
                        fact_assistant_turns.user_id AS user_id,
                        COUNT(fact_assistant_turns.message_id) AS assistant_turn_count,
                        COALESCE(SUM(fact_assistant_turns.cost_usd), 0) AS total_cost_usd,
                        MAX(fact_assistant_turns.created_at) AS last_assistant_turn_at
                    FROM fact_assistant_turns
                    GROUP BY fact_assistant_turns.user_id
                ) t ON t.user_id = u.id
                """
            )
        )

        # Rebuild feedback daily aggregates.
        conn.execute(text("DELETE FROM agg_feedback_day"))
        conn.execute(
            text(
                """
                INSERT INTO agg_feedback_day (
                    metric_date,
                    scope,
                    total_count,
                    up_count,
                    down_count,
                    time_saved_minutes,
                    time_spent_minutes
                )
                SELECT
                    DATE(mf.created_at) AS metric_date,
                    'all' AS scope,
                    COUNT(mf.id) AS total_count,
                    SUM(CASE WHEN mf.rating = 'up' THEN 1 ELSE 0 END) AS up_count,
                    SUM(CASE WHEN mf.rating = 'down' THEN 1 ELSE 0 END) AS down_count,
                    SUM(CASE WHEN mf.rating = 'up' THEN COALESCE(mf.time_saved_minutes, 0) ELSE 0 END) AS time_saved_minutes,
                    SUM(CASE WHEN mf.rating = 'down' THEN COALESCE(mf.time_spent_minutes, 0) ELSE 0 END) AS time_spent_minutes
                FROM message_feedbacks mf
                GROUP BY DATE(mf.created_at)
                """
            )
        )
        # Rebuild global admin totals snapshot.
        conn.execute(text("DELETE FROM admin_global_snapshot"))
        conn.execute(
            text(
                """
                INSERT INTO admin_global_snapshot (
                    scope,
                    total_users,
                    total_conversations,
                    total_messages,
                    total_files,
                    total_storage_bytes,
                    refreshed_at
                )
                SELECT
                    'all' AS scope,
                    (SELECT COUNT(u.id) FROM users u) AS total_users,
                    (SELECT COUNT(c.id) FROM conversations c) AS total_conversations,
                    (SELECT COALESCE(SUM(aug.messages_count), 0) FROM agg_usage_day aug WHERE aug.scope = 'all') AS total_messages,
                    (SELECT COUNT(f.id) FROM files f) AS total_files,
                    (SELECT COALESCE(SUM(f.file_size), 0) FROM files f) AS total_storage_bytes,
                    NOW() AS refreshed_at
                UNION ALL
                SELECT
                    'non_admin' AS scope,
                    (
                        SELECT COUNT(u.id)
                        FROM users u
                        WHERE LOWER(COALESCE(u.role, 'user')) <> 'admin'
                    ) AS total_users,
                    (
                        SELECT COUNT(c.id)
                        FROM conversations c
                        JOIN users u ON u.id = c.user_id
                        WHERE LOWER(COALESCE(u.role, 'user')) <> 'admin'
                    ) AS total_conversations,
                    (
                        SELECT COALESCE(SUM(aug.messages_count), 0)
                        FROM agg_usage_day aug
                        WHERE aug.scope = 'non_admin'
                    ) AS total_messages,
                    (
                        SELECT COUNT(f.id)
                        FROM files f
                        JOIN users u ON u.id = f.user_id
                        WHERE LOWER(COALESCE(u.role, 'user')) <> 'admin'
                    ) AS total_files,
                    (
                        SELECT COALESCE(SUM(f.file_size), 0)
                        FROM files f
                        JOIN users u ON u.id = f.user_id
                        WHERE LOWER(COALESCE(u.role, 'user')) <> 'admin'
                    ) AS total_storage_bytes,
                    NOW() AS refreshed_at
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO agg_feedback_day (
                    metric_date,
                    scope,
                    total_count,
                    up_count,
                    down_count,
                    time_saved_minutes,
                    time_spent_minutes
                )
                SELECT
                    DATE(mf.created_at) AS metric_date,
                    'non_admin' AS scope,
                    COUNT(mf.id) AS total_count,
                    SUM(CASE WHEN mf.rating = 'up' THEN 1 ELSE 0 END) AS up_count,
                    SUM(CASE WHEN mf.rating = 'down' THEN 1 ELSE 0 END) AS down_count,
                    SUM(CASE WHEN mf.rating = 'up' THEN COALESCE(mf.time_saved_minutes, 0) ELSE 0 END) AS time_saved_minutes,
                    SUM(CASE WHEN mf.rating = 'down' THEN COALESCE(mf.time_spent_minutes, 0) ELSE 0 END) AS time_spent_minutes
                FROM message_feedbacks mf
                JOIN users u ON u.id = mf.user_id
                WHERE LOWER(COALESCE(u.role, 'user')) <> 'admin'
                GROUP BY DATE(mf.created_at)
                """
            )
        )


if __name__ == "__main__":
    rebuild_rollups()
    print(
        "Rebuilt admin rollups: admin_user_rollup + agg_feedback_day + admin_global_snapshot"
    )
