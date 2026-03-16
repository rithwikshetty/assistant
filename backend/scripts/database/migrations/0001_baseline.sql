-- Frozen baseline schema migration.
-- This file is the authoritative DB bootstrap from Phase 2 onward.

CREATE EXTENSION IF NOT EXISTS citext;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE users (
	id UUID NOT NULL, 
	email CITEXT NOT NULL, 
	name VARCHAR(255), 
	department VARCHAR(255), 
	role VARCHAR(50) NOT NULL, 
	user_tier VARCHAR(20) NOT NULL, 
	model_override VARCHAR(100), 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	last_login_country VARCHAR(50), 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_users_role_valid CHECK (role IN ('user','admin')), 
	CONSTRAINT ck_users_user_tier_valid CHECK (user_tier IN ('default','power'))
);

CREATE INDEX ix_users_id ON users (id);

CREATE INDEX ix_users_name_trgm ON users USING gin (name gin_trgm_ops) WHERE name IS NOT NULL;

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE TABLE conversations (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	project_id UUID, 
	creation_request_id VARCHAR(64), 
	import_source_token VARCHAR(64), 
	title VARCHAR(255), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	last_message_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	parent_conversation_id UUID, 
	branch_from_message_id UUID, 
	conversation_metadata JSONB, 
	archived BOOLEAN NOT NULL, 
	archived_at TIMESTAMP WITH TIME ZONE, 
	archived_by UUID, 
	is_pinned BOOLEAN NOT NULL, 
	pinned_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_conversations_archived_requires_archived_at CHECK ((NOT archived) OR archived_at IS NOT NULL), 
	CONSTRAINT ck_conversations_pinned_requires_pinned_at CHECK ((NOT is_pinned) OR pinned_at IS NOT NULL)
);

CREATE INDEX ix_conversations_archived ON conversations (archived);

CREATE UNIQUE INDEX uq_conversations_user_creation_request ON conversations (user_id, creation_request_id) WHERE creation_request_id IS NOT NULL;

CREATE INDEX ix_conversations_metadata_gin ON conversations USING gin (conversation_metadata jsonb_path_ops);

CREATE INDEX ix_conversations_user_archived_last_message ON conversations (user_id, archived, last_message_at DESC);

CREATE UNIQUE INDEX uq_conversations_user_import_source_token ON conversations (user_id, import_source_token) WHERE import_source_token IS NOT NULL;

CREATE INDEX ix_conversations_id ON conversations (id);

CREATE INDEX ix_conversations_archived_at ON conversations (archived_at);

CREATE INDEX ix_conversations_last_message_at ON conversations (last_message_at);

CREATE INDEX ix_conversations_project_archived_last_message ON conversations (project_id, archived, last_message_at DESC);

CREATE INDEX ix_conversations_branch_from_message ON conversations (branch_from_message_id);

CREATE INDEX ix_conversations_is_pinned ON conversations (is_pinned);

CREATE INDEX ix_conversations_project_id ON conversations (project_id);

CREATE TABLE messages (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	run_id UUID, 
	role VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	text TEXT NOT NULL, 
	model_provider VARCHAR(50), 
	model_name VARCHAR(120), 
	finish_reason VARCHAR(40), 
	response_latency_ms INTEGER, 
	cost_usd NUMERIC(20, 8), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_messages_role_valid CHECK (role IN ('user','assistant','system')), 
	CONSTRAINT ck_messages_status_valid CHECK (status IN ('pending','streaming','paused','completed','failed','cancelled','awaiting_input'))
);

CREATE INDEX ix_messages_conversation_role_created ON messages (conversation_id, role, created_at DESC);

CREATE INDEX ix_messages_conversation_id ON messages (conversation_id);

CREATE INDEX ix_messages_created_at ON messages (created_at);

CREATE INDEX ix_messages_conversation_created ON messages (conversation_id, created_at ASC);

CREATE INDEX ix_messages_run_id ON messages (run_id);

CREATE INDEX ix_messages_conversation_created_id_desc ON messages (conversation_id, created_at DESC, id DESC);

CREATE INDEX ix_messages_run_role_created ON messages (run_id, role, created_at ASC);

CREATE INDEX ix_messages_status ON messages (status);

CREATE TABLE analytics_outbox (
	id BIGSERIAL NOT NULL, 
	event_type VARCHAR(80) NOT NULL, 
	event_version INTEGER NOT NULL, 
	entity_id VARCHAR(64) NOT NULL, 
	payload_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	retry_count INTEGER NOT NULL, 
	error TEXT, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_analytics_outbox_event_created ON analytics_outbox (event_type, created_at DESC);

CREATE INDEX ix_analytics_outbox_processed_at ON analytics_outbox (processed_at);

CREATE INDEX ix_analytics_outbox_event_type ON analytics_outbox (event_type);

CREATE INDEX ix_analytics_outbox_processed_created ON analytics_outbox (processed_at, created_at ASC);

CREATE INDEX ix_analytics_outbox_created_at ON analytics_outbox (created_at);

CREATE TABLE agg_model_usage_day (
	metric_date DATE NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	operation_type VARCHAR(64) NOT NULL, 
	model_provider VARCHAR(50) NOT NULL, 
	model_name VARCHAR(120) NOT NULL, 
	call_count BIGINT NOT NULL, 
	input_tokens BIGINT NOT NULL, 
	output_tokens BIGINT NOT NULL, 
	total_tokens BIGINT NOT NULL, 
	duration_seconds_sum NUMERIC(20, 6) NOT NULL, 
	cost_usd NUMERIC(20, 8) NOT NULL, 
	latency_sum_ms BIGINT NOT NULL, 
	latency_samples BIGINT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (metric_date, scope, source, operation_type, model_provider, model_name), 
	CONSTRAINT ck_agg_model_usage_day_scope_valid CHECK (scope IN ('all','non_admin')), 
	CONSTRAINT ck_agg_model_usage_day_source_valid CHECK (source IN ('chat','non_chat'))
);

CREATE INDEX ix_agg_model_usage_day_scope_source_date ON agg_model_usage_day (scope, source, metric_date DESC);

CREATE INDEX ix_agg_model_usage_day_scope_model_date ON agg_model_usage_day (scope, model_provider, model_name, metric_date DESC);

CREATE TABLE agg_usage_minute (
	bucket_minute TIMESTAMP WITH TIME ZONE NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	messages_count INTEGER NOT NULL, 
	assistant_messages_count INTEGER NOT NULL, 
	input_tokens BIGINT NOT NULL, 
	output_tokens BIGINT NOT NULL, 
	total_tokens BIGINT NOT NULL, 
	cost_usd NUMERIC(20, 8) NOT NULL, 
	latency_sum_ms BIGINT NOT NULL, 
	latency_samples INTEGER NOT NULL, 
	tool_call_count BIGINT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (bucket_minute, scope), 
	CONSTRAINT ck_agg_usage_minute_scope_valid CHECK (scope IN ('all','non_admin'))
);

CREATE TABLE agg_usage_day (
	metric_date DATE NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	messages_count INTEGER NOT NULL, 
	assistant_messages_count INTEGER NOT NULL, 
	input_tokens BIGINT NOT NULL, 
	output_tokens BIGINT NOT NULL, 
	total_tokens BIGINT NOT NULL, 
	cost_usd NUMERIC(20, 8) NOT NULL, 
	latency_sum_ms BIGINT NOT NULL, 
	latency_samples INTEGER NOT NULL, 
	tool_call_count BIGINT NOT NULL, 
	active_users INTEGER NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (metric_date, scope), 
	CONSTRAINT ck_agg_usage_day_scope_valid CHECK (scope IN ('all','non_admin'))
);

CREATE TABLE agg_model_day (
	metric_date DATE NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	model_provider VARCHAR(50) NOT NULL, 
	model_name VARCHAR(120) NOT NULL, 
	message_count INTEGER NOT NULL, 
	input_tokens BIGINT NOT NULL, 
	output_tokens BIGINT NOT NULL, 
	total_tokens BIGINT NOT NULL, 
	cost_usd NUMERIC(20, 8) NOT NULL, 
	latency_sum_ms BIGINT NOT NULL, 
	latency_samples INTEGER NOT NULL, 
	tool_call_count BIGINT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (metric_date, scope, model_provider, model_name), 
	CONSTRAINT ck_agg_model_day_scope_valid CHECK (scope IN ('all','non_admin'))
);

CREATE TABLE agg_tool_day (
	metric_date DATE NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	tool_name VARCHAR(120) NOT NULL, 
	call_count BIGINT NOT NULL, 
	error_count BIGINT NOT NULL, 
	avg_duration_ms INTEGER, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (metric_date, scope, tool_name), 
	CONSTRAINT ck_agg_tool_day_scope_valid CHECK (scope IN ('all','non_admin'))
);

CREATE TABLE agg_activity_day (
	metric_date DATE NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	activity_type VARCHAR(64) NOT NULL, 
	event_count BIGINT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (metric_date, scope, activity_type), 
	CONSTRAINT ck_agg_activity_day_scope_valid CHECK (scope IN ('all','non_admin'))
);

CREATE INDEX ix_agg_activity_day_scope_type_date ON agg_activity_day (scope, activity_type, metric_date DESC);

CREATE TABLE agg_feedback_day (
	metric_date DATE NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	total_count BIGINT NOT NULL, 
	up_count BIGINT NOT NULL, 
	down_count BIGINT NOT NULL, 
	time_saved_minutes BIGINT NOT NULL, 
	time_spent_minutes BIGINT NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (metric_date, scope), 
	CONSTRAINT ck_agg_feedback_day_scope_valid CHECK (scope IN ('all','non_admin'))
);

CREATE INDEX ix_agg_feedback_day_scope_date ON agg_feedback_day (scope, metric_date DESC);

CREATE TABLE admin_global_snapshot (
	scope VARCHAR(20) NOT NULL, 
	total_users BIGINT NOT NULL, 
	total_conversations BIGINT NOT NULL, 
	total_messages BIGINT NOT NULL, 
	total_files BIGINT NOT NULL, 
	total_storage_bytes BIGINT NOT NULL, 
	refreshed_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (scope), 
	CONSTRAINT ck_admin_global_snapshot_scope_valid CHECK (scope IN ('all','non_admin'))
);

CREATE INDEX ix_admin_global_snapshot_refreshed ON admin_global_snapshot (refreshed_at DESC);

CREATE TABLE chat_runs (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	user_message_id UUID NOT NULL, 
	request_id VARCHAR(64), 
	status VARCHAR(20) NOT NULL, 
	queued_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	provider_name VARCHAR(50), 
	model_name VARCHAR(120), 
	terminal_reason VARCHAR(80), 
	error_code VARCHAR(64), 
	error_message TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_chat_runs_conversation_user_message UNIQUE (conversation_id, user_message_id), 
	CONSTRAINT ck_chat_runs_status_valid CHECK (status IN ('queued','running','paused','completed','failed','cancelled','interrupted'))
);

CREATE INDEX ix_chat_runs_conversation_started ON chat_runs (conversation_id, queued_at DESC);

CREATE UNIQUE INDEX uq_chat_runs_conversation_request ON chat_runs (conversation_id, request_id) WHERE request_id IS NOT NULL;

CREATE INDEX ix_chat_runs_status_started ON chat_runs (status, queued_at DESC);

CREATE INDEX ix_chat_runs_user_message_id ON chat_runs (user_message_id);

CREATE INDEX ix_chat_runs_conversation_status_started ON chat_runs (conversation_id, status, queued_at DESC);

CREATE INDEX ix_chat_runs_status ON chat_runs (status);

CREATE TABLE blob_objects (
	id UUID NOT NULL, 
	storage_key VARCHAR(255) NOT NULL, 
	blob_url VARCHAR(500) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	purged_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (storage_key)
);

CREATE UNIQUE INDEX uq_blob_objects_storage_key ON blob_objects (storage_key);

CREATE INDEX ix_blob_objects_id ON blob_objects (id);

CREATE INDEX ix_blob_objects_created_at ON blob_objects (created_at DESC);

CREATE INDEX ix_blob_objects_purged_at ON blob_objects (purged_at DESC);

CREATE TABLE app_settings (
	key VARCHAR(64) NOT NULL, 
	value TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (key)
);

CREATE INDEX ix_app_settings_key ON app_settings (key);

CREATE TABLE projects (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	name VARCHAR(50) NOT NULL, 
	description TEXT, 
	custom_instructions TEXT, 
	color VARCHAR(7), 
	archived BOOLEAN NOT NULL, 
	archived_at TIMESTAMP WITH TIME ZONE, 
	archived_by UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_projects_archived_requires_archived_at CHECK ((NOT archived) OR archived_at IS NOT NULL), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(archived_by) REFERENCES users (id)
);

CREATE INDEX ix_projects_archived ON projects (archived);

CREATE INDEX ix_projects_archived_at ON projects (archived_at);

CREATE INDEX ix_projects_id ON projects (id);

CREATE TABLE skills (
	id UUID NOT NULL, 
	skill_id VARCHAR(120) NOT NULL, 
	owner_user_id UUID, 
	title VARCHAR(255) NOT NULL, 
	description TEXT, 
	when_to_use TEXT, 
	content TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_skills_status_valid CHECK (status IN ('enabled','disabled')), 
	FOREIGN KEY(owner_user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_skills_global_skill_id ON skills (skill_id) WHERE owner_user_id IS NULL;

CREATE INDEX ix_skills_owner_status ON skills (owner_user_id, status);

CREATE INDEX ix_skills_owner_user_id ON skills (owner_user_id);

CREATE INDEX ix_skills_id ON skills (id);

CREATE UNIQUE INDEX uq_skills_owner_skill_id ON skills (owner_user_id, skill_id) WHERE owner_user_id IS NOT NULL;

CREATE INDEX ix_skills_status ON skills (status);

CREATE INDEX ix_skills_skill_id ON skills (skill_id);

CREATE TABLE conversation_sector_classifications (
	conversation_id UUID NOT NULL, 
	sector VARCHAR(80) NOT NULL, 
	confidence NUMERIC(4, 3) NOT NULL, 
	user_message_count_at_classification INTEGER NOT NULL, 
	classifier_version VARCHAR(64) NOT NULL, 
	lock_hits INTEGER NOT NULL, 
	is_locked BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (conversation_id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE INDEX ix_conversation_sector_classifications_sector ON conversation_sector_classifications (sector);

CREATE INDEX ix_conversation_sector_classifications_is_locked ON conversation_sector_classifications (is_locked);

CREATE INDEX ix_conversation_sector_sector_updated ON conversation_sector_classifications (sector, updated_at DESC);

CREATE TABLE message_parts (
	id BIGSERIAL NOT NULL, 
	message_id UUID NOT NULL, 
	ordinal INTEGER NOT NULL, 
	part_type VARCHAR(40) NOT NULL, 
	phase VARCHAR(20) NOT NULL, 
	text TEXT, 
	payload_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_message_parts_message_ordinal UNIQUE (message_id, ordinal), 
	CONSTRAINT ck_message_parts_part_type_valid CHECK (part_type IN ('text','tool_call','tool_result','reasoning','divider','user_input_request','user_input_response','metadata')), 
	CONSTRAINT ck_message_parts_phase_valid CHECK (phase IN ('worklog','final')), 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE
);

CREATE INDEX ix_message_parts_created_at ON message_parts (created_at);

CREATE INDEX ix_message_parts_message_part_type ON message_parts (message_id, part_type);

CREATE INDEX ix_message_parts_message_id ON message_parts (message_id);

CREATE TABLE tool_calls (
	id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	run_id UUID, 
	tool_call_id VARCHAR(120) NOT NULL, 
	tool_name VARCHAR(120) NOT NULL, 
	arguments_jsonb JSONB NOT NULL, 
	query_text TEXT, 
	status VARCHAR(20) NOT NULL, 
	result_jsonb JSONB NOT NULL, 
	error_jsonb JSONB NOT NULL, 
	started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_tool_calls_message_tool_call UNIQUE (message_id, tool_call_id), 
	CONSTRAINT ck_tool_calls_status_valid CHECK (status IN ('pending','running','completed','failed','cancelled')), 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE SET NULL
);

CREATE INDEX ix_tool_calls_run_started ON tool_calls (run_id, started_at ASC);

CREATE INDEX ix_tool_calls_run_call_started ON tool_calls (run_id, tool_call_id, started_at DESC, id DESC);

CREATE INDEX ix_tool_calls_name_started ON tool_calls (tool_name, started_at DESC);

CREATE TABLE pending_user_inputs (
	id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	tool_call_id VARCHAR(120), 
	request_jsonb JSONB NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	resolved_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_pending_user_inputs_status_valid CHECK (status IN ('pending','resolved','cancelled')), 
	FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE
);

CREATE INDEX ix_pending_user_inputs_run_status ON pending_user_inputs (run_id, status);

CREATE INDEX ix_pending_user_inputs_run_pending_created ON pending_user_inputs (run_id, created_at DESC, id DESC) WHERE status = 'pending';

CREATE INDEX ix_pending_user_inputs_message_id ON pending_user_inputs (message_id);

CREATE INDEX ix_pending_user_inputs_message_status ON pending_user_inputs (message_id, status);

CREATE INDEX ix_pending_user_inputs_run_tool_pending_created ON pending_user_inputs (run_id, tool_call_id, created_at DESC, id DESC) WHERE status = 'pending';

CREATE INDEX ix_pending_user_inputs_created_status ON pending_user_inputs (created_at DESC, status);

CREATE INDEX ix_pending_user_inputs_run_id ON pending_user_inputs (run_id);

CREATE TABLE fact_tool_calls (
	id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	run_id UUID, 
	tool_name VARCHAR(120) NOT NULL, 
	is_error BOOLEAN NOT NULL, 
	duration_ms INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE SET NULL
);

CREATE INDEX ix_fact_tool_calls_run_created ON fact_tool_calls (run_id, created_at ASC);

CREATE INDEX ix_fact_tool_calls_tool_created ON fact_tool_calls (tool_name, created_at DESC);

CREATE INDEX ix_fact_tool_calls_created_at ON fact_tool_calls (created_at);

CREATE TABLE admin_user_rollup (
	user_id UUID NOT NULL, 
	conversation_count BIGINT NOT NULL, 
	assistant_turn_count BIGINT NOT NULL, 
	total_cost_usd NUMERIC(20, 8) NOT NULL, 
	last_assistant_turn_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_admin_user_rollup_total_cost_usd ON admin_user_rollup (total_cost_usd);

CREATE INDEX ix_admin_user_rollup_last_turn ON admin_user_rollup (last_assistant_turn_at DESC);

CREATE INDEX ix_admin_user_rollup_conversation_count ON admin_user_rollup (conversation_count);

CREATE TABLE conversation_state (
	conversation_id UUID NOT NULL, 
	last_user_message_id UUID, 
	last_assistant_message_id UUID, 
	active_run_id UUID, 
	last_user_preview VARCHAR(255), 
	awaiting_user_input BOOLEAN NOT NULL, 
	input_tokens INTEGER, 
	output_tokens INTEGER, 
	total_tokens INTEGER, 
	max_context_tokens INTEGER, 
	remaining_context_tokens INTEGER, 
	cumulative_input_tokens BIGINT, 
	cumulative_output_tokens BIGINT, 
	cumulative_total_tokens BIGINT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (conversation_id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(last_user_message_id) REFERENCES messages (id) ON DELETE SET NULL, 
	FOREIGN KEY(last_assistant_message_id) REFERENCES messages (id) ON DELETE SET NULL, 
	FOREIGN KEY(active_run_id) REFERENCES chat_runs (id) ON DELETE SET NULL
);

CREATE INDEX ix_conversation_state_last_user_message_id ON conversation_state (last_user_message_id);

CREATE INDEX ix_conversation_state_awaiting_user_input ON conversation_state (awaiting_user_input);

CREATE INDEX ix_conversation_state_last_assistant_message_id ON conversation_state (last_assistant_message_id);

CREATE INDEX ix_conversation_state_active_run_id ON conversation_state (active_run_id);

CREATE TABLE chat_run_snapshots (
	conversation_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	run_message_id UUID, 
	assistant_message_id UUID, 
	status VARCHAR(20) NOT NULL, 
	seq INTEGER NOT NULL, 
	status_label VARCHAR(255), 
	draft_text TEXT NOT NULL, 
	usage_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (conversation_id), 
	CONSTRAINT ck_chat_run_snapshots_status_valid CHECK (status IN ('running','paused')), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_message_id) REFERENCES messages (id) ON DELETE SET NULL, 
	FOREIGN KEY(assistant_message_id) REFERENCES messages (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_chat_run_snapshots_run_id ON chat_run_snapshots (run_id);

CREATE INDEX ix_chat_run_snapshots_status ON chat_run_snapshots (status);

CREATE INDEX ix_chat_run_snapshots_run_message_id ON chat_run_snapshots (run_message_id);

CREATE INDEX ix_chat_run_snapshots_status_updated ON chat_run_snapshots (status, updated_at DESC);

CREATE INDEX ix_chat_run_snapshots_assistant_message_id ON chat_run_snapshots (assistant_message_id);

CREATE TABLE chat_run_activities (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	message_id UUID, 
	item_key VARCHAR(160) NOT NULL, 
	kind VARCHAR(40) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	title VARCHAR(255), 
	summary TEXT, 
	sequence INTEGER NOT NULL, 
	payload_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_chat_run_activities_run_item_key UNIQUE (run_id, item_key), 
	CONSTRAINT ck_chat_run_activities_kind_valid CHECK (kind IN ('tool','reasoning','compaction','user_input')), 
	CONSTRAINT ck_chat_run_activities_status_valid CHECK (status IN ('pending','running','completed','failed','cancelled','info')), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE SET NULL
);

CREATE INDEX ix_chat_run_activities_message_sequence ON chat_run_activities (message_id, sequence, created_at ASC);

CREATE INDEX ix_chat_run_activities_run_id ON chat_run_activities (run_id);

CREATE INDEX ix_chat_run_activities_conversation_created ON chat_run_activities (conversation_id, created_at DESC);

CREATE INDEX ix_chat_run_activities_message_id ON chat_run_activities (message_id);

CREATE INDEX ix_chat_run_activities_run_sequence ON chat_run_activities (run_id, sequence, created_at ASC);

CREATE INDEX ix_chat_run_activities_conversation_id ON chat_run_activities (conversation_id);

CREATE TABLE chat_run_queued_turns (
	id BIGSERIAL NOT NULL, 
	conversation_id UUID NOT NULL, 
	run_id UUID NOT NULL, 
	user_message_id UUID NOT NULL, 
	blocked_by_run_id UUID, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_chat_run_queued_turns_status_valid CHECK (status IN ('queued','promoted','cancelled')), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(blocked_by_run_id) REFERENCES chat_runs (id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX ix_chat_run_queued_turns_run_id ON chat_run_queued_turns (run_id);

CREATE INDEX ix_chat_run_queued_turns_conversation_created ON chat_run_queued_turns (conversation_id, status, created_at DESC);

CREATE UNIQUE INDEX ix_chat_run_queued_turns_user_message_id ON chat_run_queued_turns (user_message_id);

CREATE INDEX ix_chat_run_queued_turns_conversation_id ON chat_run_queued_turns (conversation_id);

CREATE INDEX ix_chat_run_queued_turns_blocked_by_run_id ON chat_run_queued_turns (blocked_by_run_id);

CREATE TABLE message_feedbacks (
	id UUID NOT NULL, 
	message_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	rating VARCHAR(4) NOT NULL, 
	time_saved_minutes INTEGER, 
	improvement_notes TEXT, 
	issue_description TEXT, 
	time_spent_minutes INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_message_feedback_message_user UNIQUE (message_id, user_id), 
	CONSTRAINT ck_message_feedbacks_rating_valid CHECK (rating IN ('up','down')), 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_message_feedbacks_id ON message_feedbacks (id);

CREATE INDEX ix_message_feedbacks_message_id ON message_feedbacks (message_id);

CREATE INDEX ix_message_feedbacks_user_id ON message_feedbacks (user_id);

CREATE TABLE staged_files (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	draft_id VARCHAR(64), 
	blob_object_id UUID NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	file_type VARCHAR(50) NOT NULL, 
	file_size BIGINT NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	processing_status VARCHAR(20) NOT NULL, 
	processing_error TEXT, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	redaction_requested BOOLEAN NOT NULL, 
	redaction_applied BOOLEAN NOT NULL, 
	redacted_categories_jsonb JSONB NOT NULL, 
	parent_staged_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	expires_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_staged_files_processing_status_valid CHECK (processing_status IN ('pending','processing','completed','failed')), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(blob_object_id) REFERENCES blob_objects (id), 
	FOREIGN KEY(parent_staged_id) REFERENCES staged_files (id)
);

CREATE INDEX ix_staged_files_id ON staged_files (id);

CREATE INDEX ix_staged_files_content_hash ON staged_files (content_hash);

CREATE INDEX ix_staged_files_parent_staged_id ON staged_files (parent_staged_id);

CREATE INDEX ix_staged_files_hash_user_created ON staged_files (content_hash, user_id, created_at DESC);

CREATE INDEX ix_staged_files_draft_id ON staged_files (draft_id);

CREATE INDEX ix_staged_files_processing_status ON staged_files (processing_status);

CREATE INDEX ix_staged_files_expires_at ON staged_files (expires_at);

CREATE UNIQUE INDEX uq_staged_files_user_hash_top_level ON staged_files (user_id, content_hash) WHERE parent_staged_id IS NULL;

CREATE INDEX ix_staged_files_blob_object_id ON staged_files (blob_object_id);

CREATE INDEX ix_staged_files_processed_at ON staged_files (processed_at);

CREATE INDEX ix_staged_files_created_at ON staged_files (created_at);

CREATE TABLE bug_reports (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	user_email VARCHAR(255) NOT NULL, 
	user_name VARCHAR(255), 
	title VARCHAR(255) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	description TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_bug_reports_severity_valid CHECK (severity IN ('low','medium','high')), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_bug_reports_id ON bug_reports (id);

CREATE TABLE user_preferences (
	user_id UUID NOT NULL, 
	theme VARCHAR(10), 
	custom_instructions TEXT, 
	notification_sound BOOLEAN NOT NULL, 
	timezone VARCHAR(64), 
	locale VARCHAR(32), 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE conversation_shares (
	id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	share_token VARCHAR(64) NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	expires_at TIMESTAMP WITH TIME ZONE, 
	event_snapshot JSONB, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE INDEX ix_conversation_shares_event_snapshot_gin ON conversation_shares USING gin (event_snapshot jsonb_path_ops) WHERE event_snapshot IS NOT NULL;

CREATE INDEX ix_conversation_shares_id ON conversation_shares (id);

CREATE UNIQUE INDEX ix_conversation_shares_share_token ON conversation_shares (share_token);

CREATE TABLE refresh_tokens (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	token_hash VARCHAR(64) NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	revoked BOOLEAN NOT NULL, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	user_agent VARCHAR(500), 
	ip_address VARCHAR(45), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_refresh_tokens_user_revoked ON refresh_tokens (user_id, revoked);

CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE INDEX ix_refresh_tokens_expires ON refresh_tokens (expires_at);

CREATE UNIQUE INDEX ix_refresh_tokens_token_hash ON refresh_tokens (token_hash);

CREATE INDEX ix_refresh_tokens_id ON refresh_tokens (id);

CREATE TABLE tasks (
	id UUID NOT NULL, 
	created_by_id UUID NOT NULL, 
	category VARCHAR(255), 
	conversation_id UUID, 
	title VARCHAR(255) NOT NULL, 
	description TEXT, 
	status VARCHAR(20) NOT NULL, 
	priority VARCHAR(10) NOT NULL, 
	due_at DATE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	is_archived BOOLEAN NOT NULL, 
	archived_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_tasks_status_valid CHECK (status IN ('todo','in_progress','done')), 
	CONSTRAINT ck_tasks_priority_valid CHECK (priority IN ('low','medium','high','urgent')), 
	CONSTRAINT ck_tasks_archived_requires_archived_at CHECK ((NOT is_archived) OR archived_at IS NOT NULL), 
	FOREIGN KEY(created_by_id) REFERENCES users (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id)
);

CREATE INDEX ix_tasks_owner_status_due ON tasks (created_by_id, status, due_at) WHERE is_archived = false;

CREATE INDEX ix_tasks_category_status_due ON tasks (category, status, due_at) WHERE is_archived = false;

CREATE INDEX ix_tasks_id ON tasks (id);

CREATE INDEX ix_tasks_is_archived ON tasks (is_archived);

CREATE INDEX ix_tasks_owner_created ON tasks (created_by_id, created_at DESC);

CREATE INDEX ix_tasks_conversation_created ON tasks (conversation_id, created_at);

CREATE TABLE user_redaction_entries (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_redaction_entries_id ON user_redaction_entries (id);

CREATE INDEX ix_user_redaction_entries_user_active ON user_redaction_entries (user_id, is_active);

CREATE INDEX ix_user_redaction_entries_user_id ON user_redaction_entries (user_id);

CREATE TABLE user_activity (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	activity_type VARCHAR(50) NOT NULL, 
	target_id UUID NOT NULL, 
	conversation_id UUID, 
	project_id UUID, 
	task_id UUID, 
	run_id UUID, 
	metadata_jsonb JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_activity_user_type ON user_activity (user_id, activity_type);

CREATE INDEX ix_user_activity_type_created_user ON user_activity (activity_type, created_at, user_id);

CREATE INDEX ix_user_activity_task_created ON user_activity (task_id, created_at DESC) WHERE task_id IS NOT NULL;

CREATE INDEX ix_user_activity_type_created ON user_activity (activity_type, created_at);

CREATE INDEX ix_user_activity_target ON user_activity (target_id);

CREATE INDEX ix_user_activity_project_created ON user_activity (project_id, created_at DESC) WHERE project_id IS NOT NULL;

CREATE INDEX ix_user_activity_run_created ON user_activity (run_id, created_at DESC) WHERE run_id IS NOT NULL;

CREATE INDEX ix_user_activity_conversation_created ON user_activity (conversation_id, created_at DESC) WHERE conversation_id IS NOT NULL;

CREATE TABLE user_login_daily (
	user_id UUID NOT NULL, 
	login_date DATE NOT NULL, 
	first_login_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (user_id, login_date), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_user_login_daily_login_date ON user_login_daily (login_date, user_id);

CREATE INDEX ix_user_login_daily_user_date ON user_login_daily (user_id, login_date DESC);

CREATE TABLE project_members (
	id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	role VARCHAR(20) NOT NULL, 
	joined_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_project_member UNIQUE (project_id, user_id), 
	CONSTRAINT ck_project_members_role_valid CHECK (role IN ('member','owner')), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_project_members_user_id ON project_members (user_id);

CREATE INDEX ix_project_members_project_id ON project_members (project_id);

CREATE INDEX ix_project_members_id ON project_members (id);

CREATE TABLE project_shares (
	id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	share_token VARCHAR(64) NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	expires_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
);

CREATE INDEX ix_project_shares_project_id ON project_shares (project_id);

CREATE INDEX ix_project_shares_id ON project_shares (id);

CREATE UNIQUE INDEX ix_project_shares_share_token ON project_shares (share_token);

CREATE TABLE skill_files (
	id UUID NOT NULL, 
	skill_pk_id UUID NOT NULL, 
	path VARCHAR(1024) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	mime_type VARCHAR(255) NOT NULL, 
	storage_backend VARCHAR(20) NOT NULL, 
	blob_path VARCHAR(1024), 
	text_content TEXT, 
	binary_content BYTEA, 
	size_bytes INTEGER NOT NULL, 
	checksum_sha256 VARCHAR(64) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_skill_files_skill_path UNIQUE (skill_pk_id, path), 
	CONSTRAINT ck_skill_files_category_valid CHECK (category IN ('skill','assets','references','scripts','templates','other')), 
	CONSTRAINT ck_skill_files_storage_backend_valid CHECK (storage_backend IN ('db','blob')), 
	CONSTRAINT ck_skill_files_content_present CHECK (((storage_backend = 'db' AND blob_path IS NULL AND ((text_content IS NOT NULL) OR (binary_content IS NOT NULL))) OR (storage_backend = 'blob' AND blob_path IS NOT NULL))), 
	FOREIGN KEY(skill_pk_id) REFERENCES skills (id) ON DELETE CASCADE
);

CREATE INDEX ix_skill_files_id ON skill_files (id);

CREATE INDEX ix_skill_files_skill_pk_id ON skill_files (skill_pk_id);

CREATE INDEX ix_skill_files_skill_category ON skill_files (skill_pk_id, category);

CREATE TABLE fact_assistant_turns (
	message_id UUID NOT NULL, 
	conversation_id UUID NOT NULL, 
	run_id UUID, 
	user_id UUID, 
	project_id UUID, 
	model_provider VARCHAR(50), 
	model_name VARCHAR(120), 
	input_tokens INTEGER NOT NULL, 
	output_tokens INTEGER NOT NULL, 
	total_tokens INTEGER NOT NULL, 
	reasoning_output_tokens INTEGER NOT NULL, 
	cost_usd NUMERIC(20, 8) NOT NULL, 
	latency_ms INTEGER, 
	tool_call_count INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (message_id), 
	FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE SET NULL, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE SET NULL
);

CREATE INDEX ix_fact_assistant_turns_user_created ON fact_assistant_turns (user_id, created_at DESC);

CREATE INDEX ix_fact_assistant_turns_created_at ON fact_assistant_turns (created_at);

CREATE INDEX ix_fact_assistant_turns_model_created ON fact_assistant_turns (model_provider, model_name, created_at DESC);

CREATE INDEX ix_fact_assistant_turns_created ON fact_assistant_turns (created_at DESC);

CREATE TABLE fact_model_usage_events (
	event_id VARCHAR(64) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	operation_type VARCHAR(64) NOT NULL, 
	user_id UUID, 
	conversation_id UUID, 
	project_id UUID, 
	model_provider VARCHAR(50) NOT NULL, 
	model_name VARCHAR(120) NOT NULL, 
	call_count INTEGER NOT NULL, 
	input_tokens BIGINT NOT NULL, 
	output_tokens BIGINT NOT NULL, 
	total_tokens BIGINT NOT NULL, 
	cache_creation_input_tokens BIGINT NOT NULL, 
	cache_read_input_tokens BIGINT NOT NULL, 
	duration_seconds NUMERIC(20, 6) NOT NULL, 
	latency_ms INTEGER, 
	cost_usd NUMERIC(20, 8) NOT NULL, 
	metadata_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (event_id), 
	CONSTRAINT ck_fact_model_usage_events_source_valid CHECK (source IN ('chat','non_chat')), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL, 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE SET NULL, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE SET NULL
);

CREATE INDEX ix_fact_model_usage_events_created_at ON fact_model_usage_events (created_at);

CREATE INDEX ix_fact_model_usage_events_model_created ON fact_model_usage_events (model_provider, model_name, created_at DESC);

CREATE INDEX ix_fact_model_usage_events_source_operation_created ON fact_model_usage_events (source, operation_type, created_at DESC);

CREATE INDEX ix_fact_model_usage_events_user_created ON fact_model_usage_events (user_id, created_at DESC);

CREATE TABLE files (
	id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	conversation_id UUID, 
	project_id UUID, 
	blob_object_id UUID NOT NULL, 
	original_filename VARCHAR(255) NOT NULL, 
	file_type VARCHAR(50) NOT NULL, 
	file_size BIGINT NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	processing_status VARCHAR(20) NOT NULL, 
	indexed_chunk_count INTEGER NOT NULL, 
	indexed_at TIMESTAMP WITH TIME ZONE, 
	processing_error TEXT, 
	parent_file_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_files_exactly_one_scope CHECK ((conversation_id IS NOT NULL AND project_id IS NULL) OR (conversation_id IS NULL AND project_id IS NOT NULL)), 
	CONSTRAINT ck_files_processing_status_valid CHECK (processing_status IN ('pending','processing','completed','failed')), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(conversation_id) REFERENCES conversations (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(blob_object_id) REFERENCES blob_objects (id), 
	FOREIGN KEY(parent_file_id) REFERENCES files (id)
);

CREATE INDEX ix_files_created_at ON files (created_at);

CREATE INDEX ix_files_project_parent_created_desc ON files (project_id, parent_file_id, created_at DESC);

CREATE INDEX ix_files_hash_user_created ON files (content_hash, user_id, created_at DESC);

CREATE INDEX ix_files_id ON files (id);

CREATE INDEX ix_files_processing_status ON files (processing_status);

CREATE INDEX ix_files_project_id ON files (project_id);

CREATE INDEX ix_files_conversation ON files (conversation_id);

CREATE UNIQUE INDEX uq_files_conversation_hash_top_level ON files (conversation_id, content_hash) WHERE conversation_id IS NOT NULL AND parent_file_id IS NULL;

CREATE INDEX ix_files_hash_project_created ON files (content_hash, project_id, created_at DESC);

CREATE INDEX ix_files_blob_object_id ON files (blob_object_id);

CREATE INDEX ix_files_parent_file_id ON files (parent_file_id);

CREATE INDEX ix_files_project_parent ON files (project_id, parent_file_id);

CREATE UNIQUE INDEX uq_files_project_hash_top_level ON files (project_id, content_hash) WHERE project_id IS NOT NULL AND parent_file_id IS NULL;

CREATE INDEX ix_files_original_filename_trgm ON files USING gin (original_filename gin_trgm_ops);

CREATE INDEX ix_files_content_hash ON files (content_hash);

CREATE TABLE project_archive_jobs (
	id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	requested_by UUID NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	total_files INTEGER NOT NULL, 
	included_files INTEGER NOT NULL, 
	skipped_files INTEGER NOT NULL, 
	archive_filename VARCHAR(255), 
	storage_key VARCHAR(255), 
	blob_url TEXT, 
	error TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	expires_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_project_archive_jobs_status_valid CHECK (status IN ('pending','processing','completed','failed')), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(requested_by) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_project_archive_jobs_requester_created ON project_archive_jobs (requested_by, created_at DESC);

CREATE INDEX ix_project_archive_jobs_project_id ON project_archive_jobs (project_id);

CREATE INDEX ix_project_archive_jobs_created_at ON project_archive_jobs (created_at);

CREATE INDEX ix_project_archive_jobs_project_created ON project_archive_jobs (project_id, created_at DESC);

CREATE INDEX ix_project_archive_jobs_requested_by ON project_archive_jobs (requested_by);

CREATE INDEX ix_project_archive_jobs_completed_at ON project_archive_jobs (completed_at);

CREATE INDEX ix_project_archive_jobs_id ON project_archive_jobs (id);

CREATE INDEX ix_project_archive_jobs_status ON project_archive_jobs (status);

CREATE INDEX ix_project_archive_jobs_expires_at ON project_archive_jobs (expires_at);

CREATE TABLE staged_file_texts (
	staged_file_id UUID NOT NULL, 
	extracted_text TEXT NOT NULL, 
	char_count INTEGER NOT NULL, 
	extracted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (staged_file_id), 
	FOREIGN KEY(staged_file_id) REFERENCES staged_files (id) ON DELETE CASCADE
);

CREATE TABLE staged_file_processing_outbox (
	id BIGSERIAL NOT NULL, 
	event_type VARCHAR(80) NOT NULL, 
	event_version INTEGER NOT NULL, 
	staged_file_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	payload_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	retry_count INTEGER NOT NULL, 
	error TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(staged_file_id) REFERENCES staged_files (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX ix_staged_file_processing_outbox_processed_created ON staged_file_processing_outbox (processed_at, created_at ASC);

CREATE INDEX ix_staged_file_processing_outbox_staged_file_id ON staged_file_processing_outbox (staged_file_id);

CREATE INDEX ix_staged_file_processing_outbox_processed_at ON staged_file_processing_outbox (processed_at);

CREATE INDEX ix_staged_file_processing_outbox_event_created ON staged_file_processing_outbox (event_type, created_at DESC);

CREATE INDEX ix_staged_file_processing_outbox_user_id ON staged_file_processing_outbox (user_id);

CREATE INDEX ix_staged_file_processing_outbox_event_type ON staged_file_processing_outbox (event_type);

CREATE INDEX ix_staged_file_processing_outbox_created_at ON staged_file_processing_outbox (created_at);

CREATE TABLE task_comments (
	id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	content TEXT NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_task_comments_task_created ON task_comments (task_id, created_at);

CREATE INDEX ix_task_comments_id ON task_comments (id);

CREATE INDEX ix_task_comments_task_id ON task_comments (task_id);

CREATE TABLE task_assignments (
	id UUID NOT NULL, 
	task_id UUID NOT NULL, 
	user_id UUID NOT NULL, 
	assigned_by_id UUID NOT NULL, 
	seen_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_task_assignment_task_user UNIQUE (task_id, user_id), 
	FOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(assigned_by_id) REFERENCES users (id)
);

CREATE INDEX ix_task_assignments_task_id ON task_assignments (task_id);

CREATE INDEX ix_task_assignments_user_seen ON task_assignments (user_id, seen_at);

CREATE INDEX ix_task_assignments_user_id ON task_assignments (user_id);

CREATE INDEX ix_task_assignments_user_task ON task_assignments (user_id, task_id);

CREATE INDEX ix_task_assignments_id ON task_assignments (id);

CREATE INDEX ix_task_assignments_assigned_by_id ON task_assignments (assigned_by_id);

CREATE INDEX ix_task_assignments_task_user ON task_assignments (task_id, user_id);

CREATE TABLE file_texts (
	file_id UUID NOT NULL, 
	extracted_text TEXT NOT NULL, 
	char_count INTEGER NOT NULL, 
	extracted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (file_id), 
	FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE
);

CREATE INDEX ix_file_texts_extracted_text_trgm ON file_texts USING gin (extracted_text gin_trgm_ops);

CREATE TABLE project_file_chunks (
	id BIGSERIAL NOT NULL, 
	project_id UUID NOT NULL, 
	file_id UUID NOT NULL, 
	chunk_index INTEGER NOT NULL, 
	char_start INTEGER NOT NULL, 
	char_end INTEGER NOT NULL, 
	token_count INTEGER NOT NULL, 
	chunk_text TEXT NOT NULL, 
	chunk_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(chunk_text, ''))) STORED, 
	embedding VECTOR(1536) NOT NULL, 
	embedding_model VARCHAR(80) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_project_file_chunks_file_chunk_index UNIQUE (file_id, chunk_index), 
	CONSTRAINT ck_project_file_chunks_char_start_non_negative CHECK (char_start >= 0), 
	CONSTRAINT ck_project_file_chunks_char_range_valid CHECK (char_end >= char_start), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE
);

CREATE INDEX ix_project_file_chunks_embedding_hnsw ON project_file_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX ix_project_file_chunks_project_id ON project_file_chunks (project_id);

CREATE INDEX ix_project_file_chunks_chunk_tsv ON project_file_chunks USING gin (chunk_tsv);

CREATE INDEX ix_project_file_chunks_project_file_chunk ON project_file_chunks (project_id, file_id, chunk_index);

CREATE TABLE project_file_index_outbox (
	id BIGSERIAL NOT NULL, 
	event_type VARCHAR(80) NOT NULL, 
	event_version INTEGER NOT NULL, 
	file_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	payload_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	retry_count INTEGER NOT NULL, 
	error TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(file_id) REFERENCES files (id) ON DELETE CASCADE, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_project_file_index_outbox_event_created ON project_file_index_outbox (event_type, created_at DESC);

CREATE INDEX ix_project_file_index_outbox_project_id ON project_file_index_outbox (project_id);

CREATE INDEX ix_project_file_index_outbox_event_type ON project_file_index_outbox (event_type);

CREATE INDEX ix_project_file_index_outbox_created_at ON project_file_index_outbox (created_at);

CREATE INDEX ix_project_file_index_outbox_processed_created ON project_file_index_outbox (processed_at, created_at ASC);

CREATE INDEX ix_project_file_index_outbox_file_id ON project_file_index_outbox (file_id);

CREATE INDEX ix_project_file_index_outbox_processed_at ON project_file_index_outbox (processed_at);

CREATE TABLE project_archive_outbox (
	id BIGSERIAL NOT NULL, 
	event_type VARCHAR(80) NOT NULL, 
	event_version INTEGER NOT NULL, 
	archive_job_id UUID NOT NULL, 
	project_id UUID NOT NULL, 
	payload_jsonb JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	processed_at TIMESTAMP WITH TIME ZONE, 
	retry_count INTEGER NOT NULL, 
	error TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(archive_job_id) REFERENCES project_archive_jobs (id) ON DELETE CASCADE, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_project_archive_outbox_event_created ON project_archive_outbox (event_type, created_at DESC);

CREATE INDEX ix_project_archive_outbox_archive_job_id ON project_archive_outbox (archive_job_id);

CREATE INDEX ix_project_archive_outbox_processed_at ON project_archive_outbox (processed_at);

CREATE INDEX ix_project_archive_outbox_event_type ON project_archive_outbox (event_type);

CREATE INDEX ix_project_archive_outbox_project_id ON project_archive_outbox (project_id);

CREATE INDEX ix_project_archive_outbox_processed_created ON project_archive_outbox (processed_at, created_at ASC);

CREATE INDEX ix_project_archive_outbox_created_at ON project_archive_outbox (created_at);

ALTER TABLE conversations ADD FOREIGN KEY(branch_from_message_id) REFERENCES messages (id);

ALTER TABLE conversations ADD FOREIGN KEY(user_id) REFERENCES users (id);

ALTER TABLE conversations ADD FOREIGN KEY(archived_by) REFERENCES users (id);

ALTER TABLE chat_runs ADD FOREIGN KEY(user_message_id) REFERENCES messages (id) ON DELETE CASCADE;

ALTER TABLE conversations ADD FOREIGN KEY(parent_conversation_id) REFERENCES conversations (id);

ALTER TABLE chat_runs ADD FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE;

ALTER TABLE messages ADD FOREIGN KEY(conversation_id) REFERENCES conversations (id) ON DELETE CASCADE;

ALTER TABLE conversations ADD FOREIGN KEY(project_id) REFERENCES projects (id);

ALTER TABLE messages ADD FOREIGN KEY(run_id) REFERENCES chat_runs (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_skills_owner_status
        ON skills(owner_user_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_global_skill_id
        ON skills(skill_id)
        WHERE owner_user_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skills_owner_skill_id
        ON skills(owner_user_id, skill_id)
        WHERE owner_user_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_skill_files_skill_path
        ON skill_files(skill_pk_id, path);

CREATE INDEX IF NOT EXISTS ix_skill_files_skill_category
        ON skill_files(skill_pk_id, category);

CREATE INDEX IF NOT EXISTS ix_conversations_user_archived_last_message
        ON conversations(user_id, archived, last_message_at DESC);

CREATE INDEX IF NOT EXISTS ix_conversations_project_archived_last_message
        ON conversations(project_id, archived, last_message_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_user_creation_request
        ON conversations(user_id, creation_request_id)
        WHERE creation_request_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_user_import_source_token
        ON conversations(user_id, import_source_token)
        WHERE import_source_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_conversations_metadata_gin
        ON conversations
        USING GIN (conversation_metadata jsonb_path_ops);

CREATE INDEX IF NOT EXISTS ix_chat_runs_conversation_started
        ON chat_runs(conversation_id, queued_at DESC);

CREATE INDEX IF NOT EXISTS ix_chat_runs_status_started
        ON chat_runs(status, queued_at DESC);

CREATE INDEX IF NOT EXISTS ix_chat_runs_conversation_status_started
        ON chat_runs(conversation_id, status, queued_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_runs_conversation_request
        ON chat_runs(conversation_id, request_id)
        WHERE request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_messages_conversation_created
        ON messages(conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_messages_conversation_created_id_desc
        ON messages(conversation_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_messages_conversation_role_created
        ON messages(conversation_id, role, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_messages_run_role_created
        ON messages(run_id, role, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_message_parts_message_part_type
        ON message_parts(message_id, part_type);

CREATE INDEX IF NOT EXISTS ix_chat_run_activities_run_sequence
        ON chat_run_activities(run_id, sequence, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_chat_run_activities_message_sequence
        ON chat_run_activities(message_id, sequence, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_chat_run_activities_conversation_created
        ON chat_run_activities(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_tool_calls_run_started
        ON tool_calls(run_id, started_at ASC);

CREATE INDEX IF NOT EXISTS ix_tool_calls_run_call_started
        ON tool_calls(run_id, tool_call_id, started_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_tool_calls_name_started
        ON tool_calls(tool_name, started_at DESC);

CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_run_status
        ON pending_user_inputs(run_id, status);

CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_message_status
        ON pending_user_inputs(message_id, status);

CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_created_status
        ON pending_user_inputs(created_at DESC, status);

CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_run_pending_created
        ON pending_user_inputs(run_id, created_at DESC, id DESC)
        WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS ix_pending_user_inputs_run_tool_pending_created
        ON pending_user_inputs(run_id, tool_call_id, created_at DESC, id DESC)
        WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS ix_chat_run_snapshots_status_updated
        ON chat_run_snapshots(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_chat_run_queued_turns_conversation_created
        ON chat_run_queued_turns(conversation_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_chat_run_queued_turns_blocked_created
        ON chat_run_queued_turns(blocked_by_run_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_analytics_outbox_processed_created
        ON analytics_outbox(processed_at, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_analytics_outbox_event_created
        ON analytics_outbox(event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_fact_assistant_turns_created
        ON fact_assistant_turns(created_at DESC);

CREATE INDEX IF NOT EXISTS ix_fact_assistant_turns_user_created
        ON fact_assistant_turns(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_fact_assistant_turns_model_created
        ON fact_assistant_turns(model_provider, model_name, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_fact_tool_calls_tool_created
        ON fact_tool_calls(tool_name, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_fact_tool_calls_run_created
        ON fact_tool_calls(run_id, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_fact_model_usage_events_user_created
        ON fact_model_usage_events(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_fact_model_usage_events_model_created
        ON fact_model_usage_events(model_provider, model_name, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_fact_model_usage_events_source_operation_created
        ON fact_model_usage_events(source, operation_type, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_agg_model_usage_day_scope_source_date
        ON agg_model_usage_day(scope, source, metric_date DESC);

CREATE INDEX IF NOT EXISTS ix_agg_model_usage_day_scope_model_date
        ON agg_model_usage_day(scope, model_provider, model_name, metric_date DESC);

CREATE INDEX IF NOT EXISTS ix_users_name_trgm
        ON users USING GIN (name gin_trgm_ops)
        WHERE name IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_users_email_trgm
        ON users USING GIN ((email::text) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_agg_activity_day_scope_type_date
        ON agg_activity_day(scope, activity_type, metric_date DESC);

CREATE INDEX IF NOT EXISTS ix_agg_feedback_day_scope_date
        ON agg_feedback_day(scope, metric_date DESC);

CREATE INDEX IF NOT EXISTS ix_user_activity_user_type
        ON user_activity(user_id, activity_type);

CREATE INDEX IF NOT EXISTS ix_user_activity_type_created
        ON user_activity(activity_type, created_at);

CREATE INDEX IF NOT EXISTS ix_user_activity_type_created_user
        ON user_activity(activity_type, created_at, user_id);

CREATE INDEX IF NOT EXISTS ix_user_activity_target
        ON user_activity(target_id);

CREATE INDEX IF NOT EXISTS ix_user_activity_conversation_created
        ON user_activity(conversation_id, created_at DESC)
        WHERE conversation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_user_activity_project_created
        ON user_activity(project_id, created_at DESC)
        WHERE project_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_user_activity_task_created
        ON user_activity(task_id, created_at DESC)
        WHERE task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_user_activity_run_created
        ON user_activity(run_id, created_at DESC)
        WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_admin_user_rollup_conversation_count
        ON admin_user_rollup(conversation_count);

CREATE INDEX IF NOT EXISTS ix_admin_user_rollup_total_cost_usd
        ON admin_user_rollup(total_cost_usd);

CREATE INDEX IF NOT EXISTS ix_admin_user_rollup_last_turn
        ON admin_user_rollup(last_assistant_turn_at DESC);

CREATE INDEX IF NOT EXISTS ix_admin_global_snapshot_refreshed
        ON admin_global_snapshot(refreshed_at DESC);

CREATE INDEX IF NOT EXISTS ix_eventfeedback_user_created
        ON message_feedbacks(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_eventfeedback_rating
        ON message_feedbacks(rating, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_files_conversation_hash_top_level
        ON files(conversation_id, content_hash)
        WHERE conversation_id IS NOT NULL AND parent_file_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_files_project_hash_top_level
        ON files(project_id, content_hash)
        WHERE project_id IS NOT NULL AND parent_file_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_files_hash_user_created
        ON files(content_hash, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_files_hash_project_created
        ON files(content_hash, project_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_blob_objects_storage_key
        ON blob_objects(storage_key);

CREATE INDEX IF NOT EXISTS ix_blob_objects_created_at
        ON blob_objects(created_at DESC);

CREATE INDEX IF NOT EXISTS ix_blob_objects_purged_at
        ON blob_objects(purged_at DESC);

CREATE INDEX IF NOT EXISTS ix_files_blob_object_id
        ON files(blob_object_id);

CREATE INDEX IF NOT EXISTS ix_files_original_filename_trgm
        ON files USING GIN (original_filename gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_file_texts_extracted_text_trgm
        ON file_texts USING GIN (extracted_text gin_trgm_ops);

CREATE INDEX IF NOT EXISTS ix_project_file_chunks_project_file_chunk
        ON project_file_chunks(project_id, file_id, chunk_index);

CREATE INDEX IF NOT EXISTS ix_project_file_chunks_project_id
        ON project_file_chunks(project_id);

CREATE INDEX IF NOT EXISTS ix_project_file_chunks_chunk_tsv
        ON project_file_chunks USING GIN (chunk_tsv);

CREATE INDEX IF NOT EXISTS ix_project_file_chunks_embedding_hnsw
        ON project_file_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS ix_project_file_index_outbox_processed_created
        ON project_file_index_outbox(processed_at, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_project_file_index_outbox_event_created
        ON project_file_index_outbox(event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_project_archive_jobs_project_created
        ON project_archive_jobs(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_project_archive_jobs_requester_created
        ON project_archive_jobs(requested_by, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_project_archive_outbox_processed_created
        ON project_archive_outbox(processed_at, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_project_archive_outbox_event_created
        ON project_archive_outbox(event_type, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_staged_files_user_hash_top_level
        ON staged_files(user_id, content_hash)
        WHERE parent_staged_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_staged_files_blob_object_id
        ON staged_files(blob_object_id);

CREATE INDEX IF NOT EXISTS ix_staged_files_hash_user_created
        ON staged_files(content_hash, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_staged_files_created_at
        ON staged_files(created_at);

CREATE INDEX IF NOT EXISTS ix_staged_files_expires_at
        ON staged_files(expires_at);

CREATE INDEX IF NOT EXISTS ix_staged_file_processing_outbox_processed_created
        ON staged_file_processing_outbox(processed_at, created_at ASC);

CREATE INDEX IF NOT EXISTS ix_staged_file_processing_outbox_event_created
        ON staged_file_processing_outbox(event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_conversation_shares_event_snapshot_gin
        ON conversation_shares
        USING GIN (event_snapshot jsonb_path_ops)
        WHERE event_snapshot IS NOT NULL;
