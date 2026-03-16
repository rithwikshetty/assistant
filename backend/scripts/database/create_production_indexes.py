#!/usr/bin/env python3
"""
Create or verify the explicit production indexes for the rewritten message-store
architecture.

This script intentionally targets the new runtime + analytics schema and
excludes removed event-store tables.

Usage:
    PYTHONPATH=. python scripts/database/create_production_indexes.py

Recreate scripts now apply versioned migrations, and the baseline migration
already includes these indexes. This script remains only for repairing or
verifying an existing DB.
"""

import sys
from pathlib import Path

from sqlalchemy import text

# Add backend directory to Python path
backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from app.config.database import sync_engine


INDEXES = [
    # skills
    {
        "name": "ix_skills_owner_status",
        "table": "skills",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_skills_owner_status
        ON skills(owner_user_id, status);
        """,
        "description": "Fast custom-skill filtering by owner + status",
    },
    {
        "name": "uq_skills_global_skill_id",
        "table": "skills",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_global_skill_id
        ON skills(skill_id)
        WHERE owner_user_id IS NULL;
        """,
        "description": "Enforce unique global skill IDs",
    },
    {
        "name": "uq_skills_owner_skill_id",
        "table": "skills",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_owner_skill_id
        ON skills(owner_user_id, skill_id)
        WHERE owner_user_id IS NOT NULL;
        """,
        "description": "Allow per-user custom skills without cross-user collisions",
    },
    {
        "name": "uq_skill_files_skill_path",
        "table": "skill_files",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_files_skill_path
        ON skill_files(skill_pk_id, path);
        """,
        "description": "One file path per skill",
    },
    {
        "name": "ix_skill_files_skill_category",
        "table": "skill_files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_skill_files_skill_category
        ON skill_files(skill_pk_id, category);
        """,
        "description": "Fast per-skill category listing",
    },
    # conversations
    {
        "name": "ix_conversations_user_archived_last_message",
        "table": "conversations",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_conversations_user_archived_last_message
        ON conversations(user_id, archived, last_message_at DESC);
        """,
        "description": "Conversation list by user + archived sorted by recency",
    },
    {
        "name": "ix_conversations_project_archived_last_message",
        "table": "conversations",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_conversations_project_archived_last_message
        ON conversations(project_id, archived, last_message_at DESC);
        """,
        "description": "Project conversation list sorted by recency",
    },
    {
        "name": "uq_conversations_user_creation_request",
        "table": "conversations",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_user_creation_request
        ON conversations(user_id, creation_request_id)
        WHERE creation_request_id IS NOT NULL;
        """,
        "description": "Idempotent conversation creation",
    },
    {
        "name": "uq_conversations_user_import_source_token",
        "table": "conversations",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_user_import_source_token
        ON conversations(user_id, import_source_token)
        WHERE import_source_token IS NOT NULL;
        """,
        "description": "Idempotent conversation import",
    },
    {
        "name": "ix_conversations_metadata_gin",
        "table": "conversations",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_conversations_metadata_gin
        ON conversations
        USING GIN (conversation_metadata jsonb_path_ops);
        """,
        "description": "JSONB metadata lookup acceleration",
    },
    # chat_runs
    {
        "name": "ix_chat_runs_conversation_started",
        "table": "chat_runs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_runs_conversation_started
        ON chat_runs(conversation_id, queued_at DESC);
        """,
        "description": "Recent runs by conversation",
    },
    {
        "name": "ix_chat_runs_status_started",
        "table": "chat_runs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_runs_status_started
        ON chat_runs(status, queued_at DESC);
        """,
        "description": "Global queued/running run scans",
    },
    {
        "name": "ix_chat_runs_conversation_status_started",
        "table": "chat_runs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_runs_conversation_status_started
        ON chat_runs(conversation_id, status, queued_at DESC);
        """,
        "description": "Fast run-state lookup per conversation",
    },
    {
        "name": "uq_chat_runs_conversation_request",
        "table": "chat_runs",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_runs_conversation_request
        ON chat_runs(conversation_id, request_id)
        WHERE request_id IS NOT NULL;
        """,
        "description": "Idempotent run creation",
    },
    # messages
    {
        "name": "ix_messages_conversation_created",
        "table": "messages",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_messages_conversation_created
        ON messages(conversation_id, created_at ASC);
        """,
        "description": "Timeline pagination",
    },
    {
        "name": "ix_messages_conversation_created_id_desc",
        "table": "messages",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_messages_conversation_created_id_desc
        ON messages(conversation_id, created_at DESC, id DESC);
        """,
        "description": "Cursor-paged timeline replay by conversation + timestamp + id",
    },
    {
        "name": "ix_messages_conversation_role_created",
        "table": "messages",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_messages_conversation_role_created
        ON messages(conversation_id, role, created_at DESC);
        """,
        "description": "Role-scoped timeline queries",
    },
    {
        "name": "ix_messages_run_role_created",
        "table": "messages",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_messages_run_role_created
        ON messages(run_id, role, created_at ASC);
        """,
        "description": "Run-local message replay",
    },
    # message_parts
    {
        "name": "ix_message_parts_message_part_type",
        "table": "message_parts",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_message_parts_message_part_type
        ON message_parts(message_id, part_type);
        """,
        "description": "Fast structured part lookup",
    },
    {
        "name": "ix_chat_run_activities_run_sequence",
        "table": "chat_run_activities",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_run_activities_run_sequence
        ON chat_run_activities(run_id, sequence, created_at ASC);
        """,
        "description": "Stable per-run worklog ordering",
    },
    {
        "name": "ix_chat_run_activities_message_sequence",
        "table": "chat_run_activities",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_run_activities_message_sequence
        ON chat_run_activities(message_id, sequence, created_at ASC);
        """,
        "description": "Fast assistant-message worklog lookup",
    },
    {
        "name": "ix_chat_run_activities_conversation_created",
        "table": "chat_run_activities",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_run_activities_conversation_created
        ON chat_run_activities(conversation_id, created_at DESC);
        """,
        "description": "Conversation-level worklog retrieval",
    },
    # tool_calls + pending user input
    {
        "name": "ix_tool_calls_run_started",
        "table": "tool_calls",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_tool_calls_run_started
        ON tool_calls(run_id, started_at ASC);
        """,
        "description": "Run-local tool-call ordering",
    },
    {
        "name": "ix_tool_calls_run_call_started",
        "table": "tool_calls",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_tool_calls_run_call_started
        ON tool_calls(run_id, tool_call_id, started_at DESC, id DESC);
        """,
        "description": "Fast run+tool_call lookup during resume/result updates",
    },
    {
        "name": "ix_tool_calls_name_started",
        "table": "tool_calls",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_tool_calls_name_started
        ON tool_calls(tool_name, started_at DESC);
        """,
        "description": "Tool analytics and debugging",
    },
    {
        "name": "ix_pending_user_inputs_run_status",
        "table": "pending_user_inputs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_run_status
        ON pending_user_inputs(run_id, status);
        """,
        "description": "Pending-input resolution by run",
    },
    {
        "name": "ix_pending_user_inputs_message_status",
        "table": "pending_user_inputs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_message_status
        ON pending_user_inputs(message_id, status);
        """,
        "description": "Pending-input lookup by assistant message",
    },
    {
        "name": "ix_pending_user_inputs_created_status",
        "table": "pending_user_inputs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_created_status
        ON pending_user_inputs(created_at DESC, status);
        """,
        "description": "Date-window + status aggregation for request-user-input metrics",
    },
    {
        "name": "ix_pending_user_inputs_run_pending_created",
        "table": "pending_user_inputs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_run_pending_created
        ON pending_user_inputs(run_id, created_at DESC, id DESC)
        WHERE status = 'pending';
        """,
        "description": "Postgres partial index for pending queue head lookup by run",
    },
    {
        "name": "ix_pending_user_inputs_run_tool_pending_created",
        "table": "pending_user_inputs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_run_tool_pending_created
        ON pending_user_inputs(run_id, tool_call_id, created_at DESC, id DESC)
        WHERE status = 'pending';
        """,
        "description": "Postgres partial index for pending lookup by run+tool_call",
    },
    # active run snapshots + queued turns
    {
        "name": "ix_chat_run_snapshots_status_updated",
        "table": "chat_run_snapshots",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_run_snapshots_status_updated
        ON chat_run_snapshots(status, updated_at DESC);
        """,
        "description": "Active/paused run recovery scans by status",
    },
    {
        "name": "ix_chat_run_queued_turns_conversation_created",
        "table": "chat_run_queued_turns",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_run_queued_turns_conversation_created
        ON chat_run_queued_turns(conversation_id, status, created_at DESC);
        """,
        "description": "Queued-turn FIFO scans per conversation",
    },
    {
        "name": "ix_chat_run_queued_turns_blocked_created",
        "table": "chat_run_queued_turns",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_chat_run_queued_turns_blocked_created
        ON chat_run_queued_turns(blocked_by_run_id, status, created_at DESC);
        """,
        "description": "Queued-turn promotion scans by blocked run",
    },
    # analytics
    {
        "name": "ix_analytics_outbox_processed_created",
        "table": "analytics_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_analytics_outbox_processed_created
        ON analytics_outbox(processed_at, created_at ASC);
        """,
        "description": "Outbox worker queue scan",
    },
    {
        "name": "ix_analytics_outbox_event_created",
        "table": "analytics_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_analytics_outbox_event_created
        ON analytics_outbox(event_type, created_at DESC);
        """,
        "description": "Event-type backfills",
    },
    {
        "name": "ix_fact_assistant_turns_created",
        "table": "fact_assistant_turns",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_assistant_turns_created
        ON fact_assistant_turns(created_at DESC);
        """,
        "description": "Dashboard time-range reads",
    },
    {
        "name": "ix_fact_assistant_turns_user_created",
        "table": "fact_assistant_turns",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_assistant_turns_user_created
        ON fact_assistant_turns(user_id, created_at DESC);
        """,
        "description": "Per-user assistant usage",
    },
    {
        "name": "ix_fact_assistant_turns_model_created",
        "table": "fact_assistant_turns",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_assistant_turns_model_created
        ON fact_assistant_turns(model_provider, model_name, created_at DESC);
        """,
        "description": "Model breakdown over time",
    },
    {
        "name": "ix_fact_tool_calls_tool_created",
        "table": "fact_tool_calls",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_tool_calls_tool_created
        ON fact_tool_calls(tool_name, created_at DESC);
        """,
        "description": "Tool usage trend reads",
    },
    {
        "name": "ix_fact_tool_calls_run_created",
        "table": "fact_tool_calls",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_tool_calls_run_created
        ON fact_tool_calls(run_id, created_at ASC);
        """,
        "description": "Run-local tool analysis",
    },
    {
        "name": "ix_fact_model_usage_events_user_created",
        "table": "fact_model_usage_events",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_model_usage_events_user_created
        ON fact_model_usage_events(user_id, created_at DESC);
        """,
        "description": "Per-user non-chat model usage",
    },
    {
        "name": "ix_fact_model_usage_events_model_created",
        "table": "fact_model_usage_events",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_model_usage_events_model_created
        ON fact_model_usage_events(model_provider, model_name, created_at DESC);
        """,
        "description": "Non-chat model breakdown over time",
    },
    {
        "name": "ix_fact_model_usage_events_source_operation_created",
        "table": "fact_model_usage_events",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_fact_model_usage_events_source_operation_created
        ON fact_model_usage_events(source, operation_type, created_at DESC);
        """,
        "description": "Non-chat operation usage trend reads",
    },
    {
        "name": "ix_agg_model_usage_day_scope_source_date",
        "table": "agg_model_usage_day",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_agg_model_usage_day_scope_source_date
        ON agg_model_usage_day(scope, source, metric_date DESC);
        """,
        "description": "Model usage aggregates by scope/source/date",
    },
    {
        "name": "ix_agg_model_usage_day_scope_model_date",
        "table": "agg_model_usage_day",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_agg_model_usage_day_scope_model_date
        ON agg_model_usage_day(scope, model_provider, model_name, metric_date DESC);
        """,
        "description": "Model usage aggregates by scope/model/date",
    },
    {
        "name": "ix_users_name_trgm",
        "table": "users",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_users_name_trgm
        ON users USING GIN (name gin_trgm_ops)
        WHERE name IS NOT NULL;
        """,
        "description": "Fast case-insensitive/fuzzy name search",
    },
    {
        "name": "ix_users_email_trgm",
        "table": "users",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_users_email_trgm
        ON users USING GIN ((email::text) gin_trgm_ops);
        """,
        "description": "Fast case-insensitive/fuzzy email search",
    },
    {
        "name": "ix_agg_activity_day_scope_type_date",
        "table": "agg_activity_day",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_agg_activity_day_scope_type_date
        ON agg_activity_day(scope, activity_type, metric_date DESC);
        """,
        "description": "Behavioral activity aggregates by scope/type/date",
    },
    {
        "name": "ix_agg_feedback_day_scope_date",
        "table": "agg_feedback_day",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_agg_feedback_day_scope_date
        ON agg_feedback_day(scope, metric_date DESC);
        """,
        "description": "Feedback/time-impact aggregates by scope/date",
    },
    {
        "name": "ix_user_activity_user_type",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_user_type
        ON user_activity(user_id, activity_type);
        """,
        "description": "User-centric activity lookup by type",
    },
    {
        "name": "ix_user_activity_type_created",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_type_created
        ON user_activity(activity_type, created_at);
        """,
        "description": "Activity trend scans by type/time",
    },
    {
        "name": "ix_user_activity_type_created_user",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_type_created_user
        ON user_activity(activity_type, created_at, user_id);
        """,
        "description": "Primary KPI slice: type/time/user",
    },
    {
        "name": "ix_user_activity_target",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_target
        ON user_activity(target_id);
        """,
        "description": "Entity-linked activity lookup",
    },
    {
        "name": "ix_user_activity_conversation_created",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_conversation_created
        ON user_activity(conversation_id, created_at DESC)
        WHERE conversation_id IS NOT NULL;
        """,
        "description": "Conversation-linked activity scans",
    },
    {
        "name": "ix_user_activity_project_created",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_project_created
        ON user_activity(project_id, created_at DESC)
        WHERE project_id IS NOT NULL;
        """,
        "description": "Project-linked activity scans",
    },
    {
        "name": "ix_user_activity_task_created",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_task_created
        ON user_activity(task_id, created_at DESC)
        WHERE task_id IS NOT NULL;
        """,
        "description": "Task-linked activity scans",
    },
    {
        "name": "ix_user_activity_run_created",
        "table": "user_activity",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_user_activity_run_created
        ON user_activity(run_id, created_at DESC)
        WHERE run_id IS NOT NULL;
        """,
        "description": "Run-linked activity scans",
    },
    {
        "name": "ix_admin_user_rollup_conversation_count",
        "table": "admin_user_rollup",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_admin_user_rollup_conversation_count
        ON admin_user_rollup(conversation_count);
        """,
        "description": "Users-tab sort by conversation count",
    },
    {
        "name": "ix_admin_user_rollup_total_cost_usd",
        "table": "admin_user_rollup",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_admin_user_rollup_total_cost_usd
        ON admin_user_rollup(total_cost_usd);
        """,
        "description": "Users-tab sort by spend",
    },
    {
        "name": "ix_admin_user_rollup_last_turn",
        "table": "admin_user_rollup",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_admin_user_rollup_last_turn
        ON admin_user_rollup(last_assistant_turn_at DESC);
        """,
        "description": "Users-tab recency analytics lookup",
    },
    {
        "name": "ix_admin_global_snapshot_refreshed",
        "table": "admin_global_snapshot",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_admin_global_snapshot_refreshed
        ON admin_global_snapshot(refreshed_at DESC);
        """,
        "description": "Fast freshest-snapshot lookup for admin totals",
    },
    # supporting tables still used in runtime/admin flows
    {
        "name": "ix_eventfeedback_user_created",
        "table": "message_feedbacks",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_eventfeedback_user_created
        ON message_feedbacks(user_id, created_at DESC);
        """,
        "description": "Feedback reads by user/date",
    },
    {
        "name": "ix_eventfeedback_rating",
        "table": "message_feedbacks",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_eventfeedback_rating
        ON message_feedbacks(rating, created_at DESC);
        """,
        "description": "Feedback reads by rating/date",
    },
    {
        "name": "uq_files_conversation_hash_top_level",
        "table": "files",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_files_conversation_hash_top_level
        ON files(conversation_id, content_hash)
        WHERE conversation_id IS NOT NULL AND parent_file_id IS NULL;
        """,
        "description": "Prevents duplicate top-level files in one conversation scope",
    },
    {
        "name": "uq_files_project_hash_top_level",
        "table": "files",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_files_project_hash_top_level
        ON files(project_id, content_hash)
        WHERE project_id IS NOT NULL AND parent_file_id IS NULL;
        """,
        "description": "Prevents duplicate top-level knowledge files in one project scope",
    },
    {
        "name": "ix_files_hash_user_created",
        "table": "files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_files_hash_user_created
        ON files(content_hash, user_id, created_at DESC);
        """,
        "description": "File dedup checks per user",
    },
    {
        "name": "ix_files_hash_project_created",
        "table": "files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_files_hash_project_created
        ON files(content_hash, project_id, created_at DESC);
        """,
        "description": "File dedup checks per project",
    },
    {
        "name": "uq_blob_objects_storage_key",
        "table": "blob_objects",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_blob_objects_storage_key
        ON blob_objects(storage_key);
        """,
        "description": "Enforce unique blob storage key ownership",
    },
    {
        "name": "ix_blob_objects_created_at",
        "table": "blob_objects",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_blob_objects_created_at
        ON blob_objects(created_at DESC);
        """,
        "description": "Blob lifecycle recency lookup",
    },
    {
        "name": "ix_blob_objects_purged_at",
        "table": "blob_objects",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_blob_objects_purged_at
        ON blob_objects(purged_at DESC);
        """,
        "description": "Blob purge auditing and cleanup scans",
    },
    {
        "name": "ix_files_blob_object_id",
        "table": "files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_files_blob_object_id
        ON files(blob_object_id);
        """,
        "description": "Fast file-to-blob ownership lookup",
    },
    {
        "name": "ix_files_original_filename_trgm",
        "table": "files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_files_original_filename_trgm
        ON files USING GIN (original_filename gin_trgm_ops);
        """,
        "description": "Fast case-insensitive filename search",
    },
    {
        "name": "ix_file_texts_extracted_text_trgm",
        "table": "file_texts",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_file_texts_extracted_text_trgm
        ON file_texts USING GIN (extracted_text gin_trgm_ops);
        """,
        "description": "Fast case-insensitive content search for extracted conversation file text",
    },
    {
        "name": "ix_project_file_chunks_project_file_chunk",
        "table": "project_file_chunks",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_file_chunks_project_file_chunk
        ON project_file_chunks(project_id, file_id, chunk_index);
        """,
        "description": "Fast per-project file chunk ordering and lookup",
    },
    {
        "name": "ix_project_file_chunks_project_id",
        "table": "project_file_chunks",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_file_chunks_project_id
        ON project_file_chunks(project_id);
        """,
        "description": "Project-scoped chunk filtering",
    },
    {
        "name": "ix_project_file_chunks_chunk_tsv",
        "table": "project_file_chunks",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_file_chunks_chunk_tsv
        ON project_file_chunks USING GIN (chunk_tsv);
        """,
        "description": "Full-text search acceleration on chunk text",
    },
    {
        "name": "ix_project_file_chunks_embedding_hnsw",
        "table": "project_file_chunks",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_file_chunks_embedding_hnsw
        ON project_file_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);
        """,
        "description": "Approximate nearest-neighbor vector search acceleration",
    },
    {
        "name": "ix_project_file_index_outbox_processed_created",
        "table": "project_file_index_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_file_index_outbox_processed_created
        ON project_file_index_outbox(processed_at, created_at ASC);
        """,
        "description": "Pending outbox scan efficiency",
    },
    {
        "name": "ix_project_file_index_outbox_event_created",
        "table": "project_file_index_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_file_index_outbox_event_created
        ON project_file_index_outbox(event_type, created_at DESC);
        """,
        "description": "Event-type scoped outbox processing",
    },
    {
        "name": "ix_project_archive_jobs_project_created",
        "table": "project_archive_jobs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_archive_jobs_project_created
        ON project_archive_jobs(project_id, created_at DESC);
        """,
        "description": "Project archive job history by project",
    },
    {
        "name": "ix_project_archive_jobs_requester_created",
        "table": "project_archive_jobs",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_archive_jobs_requester_created
        ON project_archive_jobs(requested_by, created_at DESC);
        """,
        "description": "Project archive job history by requester",
    },
    {
        "name": "ix_project_archive_outbox_processed_created",
        "table": "project_archive_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_archive_outbox_processed_created
        ON project_archive_outbox(processed_at, created_at ASC);
        """,
        "description": "Pending project archive outbox scan",
    },
    {
        "name": "ix_project_archive_outbox_event_created",
        "table": "project_archive_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_project_archive_outbox_event_created
        ON project_archive_outbox(event_type, created_at DESC);
        """,
        "description": "Project archive event-type backfills",
    },
    {
        "name": "uq_staged_files_user_hash_top_level",
        "table": "staged_files",
        "sql": """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_staged_files_user_hash_top_level
        ON staged_files(user_id, content_hash)
        WHERE parent_staged_id IS NULL;
        """,
        "description": "Prevents duplicate top-level staged files per user",
    },
    {
        "name": "ix_staged_files_blob_object_id",
        "table": "staged_files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_staged_files_blob_object_id
        ON staged_files(blob_object_id);
        """,
        "description": "Fast staged-file-to-blob ownership lookup",
    },
    {
        "name": "ix_staged_files_hash_user_created",
        "table": "staged_files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_staged_files_hash_user_created
        ON staged_files(content_hash, user_id, created_at DESC);
        """,
        "description": "Recent staged-file dedupe lookup by user + content hash",
    },
    {
        "name": "ix_staged_files_created_at",
        "table": "staged_files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_staged_files_created_at
        ON staged_files(created_at);
        """,
        "description": "Staged-file recency scans",
    },
    {
        "name": "ix_staged_files_expires_at",
        "table": "staged_files",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_staged_files_expires_at
        ON staged_files(expires_at);
        """,
        "description": "Staged-file expiry cleanup scans",
    },
    {
        "name": "ix_staged_file_processing_outbox_processed_created",
        "table": "staged_file_processing_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_staged_file_processing_outbox_processed_created
        ON staged_file_processing_outbox(processed_at, created_at ASC);
        """,
        "description": "Pending staged-file processing outbox scan",
    },
    {
        "name": "ix_staged_file_processing_outbox_event_created",
        "table": "staged_file_processing_outbox",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_staged_file_processing_outbox_event_created
        ON staged_file_processing_outbox(event_type, created_at DESC);
        """,
        "description": "Staged-file processing event-type backfills",
    },
    {
        "name": "ix_conversation_shares_event_snapshot_gin",
        "table": "conversation_shares",
        "sql": """
        CREATE INDEX IF NOT EXISTS ix_conversation_shares_event_snapshot_gin
        ON conversation_shares
        USING GIN (event_snapshot jsonb_path_ops)
        WHERE event_snapshot IS NOT NULL;
        """,
        "description": "JSONB message snapshot lookup acceleration",
    },
]


def check_table_exists(conn, table_name: str) -> bool:
    query = text(
        """
        SELECT to_regclass(:qualified_name) IS NOT NULL
        """
    )
    result = conn.execute(query, {"qualified_name": f"public.{table_name}"})
    return bool(result.scalar())


def check_index_exists(conn, index_name: str) -> bool:
    query = text(
        """
        SELECT to_regclass(:qualified_name) IS NOT NULL
        """
    )
    result = conn.execute(query, {"qualified_name": f"public.{index_name}"})
    return bool(result.scalar())


def ensure_postgres_extensions(conn) -> None:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS citext"))
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    conn.commit()


def create_production_indexes() -> None:
    print("\n" + "=" * 80)
    print("Creating Production Database Indexes (Message-Store Schema)")
    print("=" * 80)

    created = 0
    skipped = 0
    skipped_missing_table = 0
    failed = 0

    with sync_engine.connect() as conn:
        ensure_postgres_extensions(conn)
        for idx in INDEXES:
            print(f"\n- {idx['name']} ({idx['table']})")
            print(f"  Purpose: {idx['description']}")

            if not check_table_exists(conn, idx["table"]):
                print("  SKIPPED: table does not exist")
                skipped_missing_table += 1
                continue

            if check_index_exists(conn, idx["name"]):
                print("  SKIPPED: index already exists")
                skipped += 1
                continue

            try:
                conn.execute(text(idx["sql"]))
                conn.commit()
                print("  CREATED")
                created += 1
            except Exception as exc:
                print(f"  FAILED: {exc}")
                conn.rollback()
                failed += 1

    print("\n" + "=" * 80)
    print(
        "Summary: "
        f"{created} created, {skipped} existing, "
        f"{skipped_missing_table} missing-table skips, {failed} failed"
    )
    print("=" * 80)

    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    try:
        create_production_indexes()
    except Exception as exc:
        print(f"\nError: {exc}")
        sys.exit(1)
