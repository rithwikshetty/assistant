import json
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Optional, List, Union
from pydantic import AliasChoices, Field, field_validator, model_validator
from .dev_runtime import (
    build_dynamic_database_url,
    build_dynamic_redis_url,
    build_dynamic_sandbox_url,
    get_reserved_service_url,
)
from .file_types import get_allowed_file_types_list


class SettingsValidationError(ValueError):
    """Raised when critical configuration values are missing or insecure."""
    pass

class Settings(BaseSettings):
    # Database (PostgreSQL)
    database_url: str = ""
    
    # JWT
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    
    # AI Models
    openai_api_key: Optional[str] = None  # Primary chat/runtime key
    
    # API
    cors_origins: Union[str, List[str]] = []
    cors_origin_regex: Optional[str] = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"
    frontend_url: Optional[str] = None  # Optional override for generated share URLs
    api_base_url: Optional[str] = None
    debug: bool = False
    log_level: str = "INFO"
    log_format: str = "auto"  # auto|pretty|json
    log_color: str = "auto"   # auto|on|off
    log_request_slow_ms: int = 1500
    log_sqlalchemy_level: str = "WARNING"

    # Local single-user workspace identity
    local_user_email: str = "assistant@local"
    local_user_name: str = "assistant"
    local_user_department: str = "Local"
    local_user_role: str = "user"
    local_user_tier: str = "power"

    # Code execution sandbox
    sandbox_backend: str = "docker_sidecar"
    sandbox_url: str = ""

    # Redis - runtime coordination
    redis_url: str = ""
    redis_ssl_cert_reqs: str = "required"  # required|optional|none for rediss:// URLs
    redis_ssl_ca_certs: Optional[str] = None  # Optional CA bundle path for Redis TLS

    # Redis Streams tuning (chat event streaming)
    redis_stream_max_len: int = 5000       # MAXLEN for XADD (cap per conversation)
    redis_stream_grace_period: int = 300   # TTL after completion (seconds)
    redis_stream_initial_ttl: int = 43200  # Initial/active TTL while stream is running (seconds)
    redis_stream_user_set_ttl: int = 43200 # TTL for per-user active stream set (seconds)
    redis_stream_xread_block_ms: int = 10000  # Live stream blocking read timeout (ms)
    redis_stream_heartbeat_interval: int = 30  # Producer heartbeat interval to refresh TTLs (seconds)
    stream_connect_wait_seconds: float = Field(
        default=8.0,
        validation_alias=AliasChoices(
            "stream_connect_wait_seconds",
            "stream_registration_wait_seconds",
            "STREAM_CONNECT_WAIT_SECONDS",
            "STREAM_REGISTRATION_WAIT_SECONDS",
        ),
    )
    stream_reconnect_wait_seconds: float = Field(
        default=1.5,
        validation_alias=AliasChoices(
            "stream_reconnect_wait_seconds",
            "STREAM_RECONNECT_WAIT_SECONDS",
        ),
    )
    stream_checkpoint_interval_seconds: float = 2.0  # Persist partial assistant output every N seconds
    redis_max_connections: int = 200       # Async connection pool size
    run_supervisor_local_concurrency: int = 8
    run_supervisor_global_concurrency: int = 100
    run_supervisor_reader_count: int = 4
    run_supervisor_block_ms: int = 1500
    run_supervisor_queue_max_len: int = 20000

    # Token count threshold for calling the standalone /responses/compact
    # endpoint before a model turn. Intentionally kept at 230K even after the
    # GPT-5.4 context-window upgrade to preserve current latency behavior.
    openai_compact_trigger_tokens: int = 230_000
    
    # Chat model fallbacks used when admin settings are not yet initialized.
    chat_default_model: str = "gpt-5.4"
    chat_power_model: str = "gpt-5.4"
    chat_reasoning_effort: str = "medium"
    # Optional JSON map for per-model token pricing overrides.
    # Key format: "<provider>:<model_prefix>".
    # Value fields: input_price, cache_creation_price, cache_read_price, output_price.
    model_pricing_overrides: dict[str, dict[str, Any]] = {}
    # Optional JSON map for per-model duration pricing overrides (USD per second).
    # Key format: "<provider>:<model_prefix>".
    duration_pricing_overrides: dict[str, Any] = {}

    # UI/metrics context window override (tokens) — disabled by default
    display_context_window_tokens: int | None = None

    # Admin analytics snapshot freshness window (seconds).
    # Snapshot reads avoid repeated full-table totals on hot admin routes.
    admin_global_snapshot_max_age_seconds: int = 300
    analytics_activity_outbox_batch_size: int = 250
    analytics_activity_outbox_beat_interval_seconds: int = 30
    analytics_assistant_turn_outbox_batch_size: int = 250
    analytics_assistant_turn_outbox_beat_interval_seconds: int = 30
    analytics_model_usage_outbox_batch_size: int = 250
    analytics_model_usage_outbox_beat_interval_seconds: int = 30
    project_file_index_outbox_batch_size: int = 100
    project_file_index_outbox_beat_interval_seconds: int = 30
    project_file_index_outbox_max_retries: int = 25
    staged_file_processing_outbox_batch_size: int = 100
    staged_file_processing_outbox_beat_interval_seconds: int = 30
    staged_file_processing_outbox_max_retries: int = 25
    project_archive_outbox_batch_size: int = 20
    project_archive_outbox_beat_interval_seconds: int = 30
    project_archive_outbox_max_retries: int = 25
    project_file_index_parallel_workers: int = 10
    project_file_chunk_size_chars: int = 4000
    project_file_chunk_overlap_chars: int = 600
    project_file_search_excerpt_max_chars: int = 900
    project_file_embedding_batch_size: int = 64
    project_file_dense_candidate_limit: int = 80
    project_file_sparse_candidate_limit: int = 80
    project_file_search_top_k: int = 10
    project_file_hybrid_rrf_k: int = 60
    project_file_hybrid_dense_weight: float = 0.65
    project_file_embedding_model: str = "text-embedding-3-small"
    analytics_activity_outbox_dispatch_cooldown_seconds: int = 2
    analytics_assistant_turn_outbox_dispatch_cooldown_seconds: int = 2
    analytics_model_usage_outbox_dispatch_cooldown_seconds: int = 2
    analytics_outbox_max_retries: int = 25
    analytics_outbox_cleanup_batch_size: int = 1000
    analytics_outbox_cleanup_retention_days: int = 14
    analytics_outbox_cleanup_beat_interval_seconds: int = 3600

    @field_validator('cors_origins', mode='before')
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',') if origin.strip()]
        return v

    @field_validator('log_level', mode='before')
    @classmethod
    def validate_log_level(cls, v):
        normalized = str(v or "INFO").strip().upper()
        return normalized if normalized in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"} else "INFO"

    @staticmethod
    def _parse_json_mapping(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            try:
                parsed = json.loads(stripped)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @field_validator('model_pricing_overrides', mode='before')
    @classmethod
    def validate_model_pricing_overrides(cls, v):
        parsed = cls._parse_json_mapping(v)
        normalized: dict[str, dict[str, Any]] = {}
        for raw_key, raw_value in parsed.items():
            key = str(raw_key or "").strip().lower()
            if ":" not in key or not isinstance(raw_value, dict):
                continue
            normalized[key] = dict(raw_value)
        return normalized

    @field_validator('duration_pricing_overrides', mode='before')
    @classmethod
    def validate_duration_pricing_overrides(cls, v):
        parsed = cls._parse_json_mapping(v)
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in parsed.items():
            key = str(raw_key or "").strip().lower()
            if ":" not in key:
                continue
            normalized[key] = raw_value
        return normalized

    @field_validator('log_sqlalchemy_level', mode='before')
    @classmethod
    def validate_log_sqlalchemy_level(cls, v):
        normalized = str(v or "WARNING").strip().upper()
        return normalized if normalized in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"} else "WARNING"

    @field_validator('log_format', mode='before')
    @classmethod
    def validate_log_format(cls, v):
        normalized = str(v or "auto").strip().lower()
        return normalized if normalized in {"auto", "pretty", "json"} else "auto"

    @field_validator('log_color', mode='before')
    @classmethod
    def validate_log_color(cls, v):
        normalized = str(v or "auto").strip().lower()
        if normalized in {"on", "true", "1", "always"}:
            return "on"
        if normalized in {"off", "false", "0", "never"}:
            return "off"
        return "auto"

    @field_validator('log_request_slow_ms', mode='before')
    @classmethod
    def validate_log_request_slow_ms(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 1500
        return value if value > 0 else 1500

    @field_validator('redis_ssl_cert_reqs', mode='before')
    @classmethod
    def validate_redis_ssl_cert_reqs(cls, v):
        normalized = str(v or "required").strip().lower()
        return normalized if normalized in {"required", "optional", "none"} else "required"

    @field_validator('stream_connect_wait_seconds', mode='before')
    @classmethod
    def validate_stream_connect_wait_seconds(cls, v):
        try:
            value = float(v)
        except (TypeError, ValueError):
            return 8.0
        return max(1.0, min(30.0, value))

    @field_validator('stream_reconnect_wait_seconds', mode='before')
    @classmethod
    def validate_stream_reconnect_wait_seconds(cls, v):
        try:
            value = float(v)
        except (TypeError, ValueError):
            return 1.5
        return max(0.1, min(5.0, value))

    @field_validator('openai_compact_trigger_tokens', mode='before')
    @classmethod
    def validate_openai_compact_trigger_tokens(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 180_000
        return max(10_000, value)

    @field_validator('chat_reasoning_effort', mode='before')
    @classmethod
    def validate_chat_reasoning_effort(cls, v):
        normalized = str(v or "medium").strip().lower()
        return normalized if normalized in {"none", "low", "medium", "high", "xhigh"} else "medium"

    @field_validator('admin_global_snapshot_max_age_seconds', mode='before')
    @classmethod
    def validate_admin_global_snapshot_max_age_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 300
        return max(30, value)

    @field_validator('analytics_activity_outbox_batch_size', mode='before')
    @classmethod
    def validate_analytics_activity_outbox_batch_size(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 250
        return max(1, value)

    @field_validator('analytics_assistant_turn_outbox_batch_size', mode='before')
    @classmethod
    def validate_analytics_assistant_turn_outbox_batch_size(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 250
        return max(1, value)

    @field_validator('analytics_model_usage_outbox_batch_size', mode='before')
    @classmethod
    def validate_analytics_model_usage_outbox_batch_size(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 250
        return max(1, value)

    @field_validator('analytics_activity_outbox_beat_interval_seconds', mode='before')
    @classmethod
    def validate_analytics_activity_outbox_beat_interval_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 30
        return max(5, value)

    @field_validator('analytics_assistant_turn_outbox_beat_interval_seconds', mode='before')
    @classmethod
    def validate_analytics_assistant_turn_outbox_beat_interval_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 30
        return max(5, value)

    @field_validator('analytics_model_usage_outbox_beat_interval_seconds', mode='before')
    @classmethod
    def validate_analytics_model_usage_outbox_beat_interval_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 30
        return max(5, value)

    @field_validator('project_file_index_outbox_batch_size', mode='before')
    @classmethod
    def validate_project_file_index_outbox_batch_size(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 100
        return max(1, value)

    @field_validator('project_file_index_outbox_beat_interval_seconds', mode='before')
    @classmethod
    def validate_project_file_index_outbox_beat_interval_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 30
        return max(5, value)

    @field_validator('project_file_index_outbox_max_retries', mode='before')
    @classmethod
    def validate_project_file_index_outbox_max_retries(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 25
        return max(1, value)

    @field_validator('project_file_index_parallel_workers', mode='before')
    @classmethod
    def validate_project_file_index_parallel_workers(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 10
        return max(1, min(32, value))

    @field_validator('project_file_chunk_size_chars', mode='before')
    @classmethod
    def validate_project_file_chunk_size_chars(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 4000
        return max(500, value)

    @field_validator('project_file_chunk_overlap_chars', mode='before')
    @classmethod
    def validate_project_file_chunk_overlap_chars(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 600
        return max(0, value)

    @field_validator('project_file_search_excerpt_max_chars', mode='before')
    @classmethod
    def validate_project_file_search_excerpt_max_chars(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 900
        return max(120, min(5000, value))

    @field_validator('project_file_embedding_batch_size', mode='before')
    @classmethod
    def validate_project_file_embedding_batch_size(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 64
        return max(1, min(256, value))

    @field_validator('project_file_dense_candidate_limit', mode='before')
    @classmethod
    def validate_project_file_dense_candidate_limit(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 80
        return max(1, value)

    @field_validator('project_file_sparse_candidate_limit', mode='before')
    @classmethod
    def validate_project_file_sparse_candidate_limit(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 80
        return max(1, value)

    @field_validator('project_file_search_top_k', mode='before')
    @classmethod
    def validate_project_file_search_top_k(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 10
        return max(1, min(50, value))

    @field_validator('project_file_hybrid_rrf_k', mode='before')
    @classmethod
    def validate_project_file_hybrid_rrf_k(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 60
        return max(1, value)

    @field_validator('project_file_hybrid_dense_weight', mode='before')
    @classmethod
    def validate_project_file_hybrid_dense_weight(cls, v):
        try:
            value = float(v)
        except (TypeError, ValueError):
            return 0.65
        return min(1.0, max(0.0, value))

    @field_validator('project_file_embedding_model', mode='before')
    @classmethod
    def validate_project_file_embedding_model(cls, v):
        normalized = str(v or "text-embedding-3-small").strip()
        # Project indexing schema is fixed to vector(1536).
        return "text-embedding-3-small" if normalized != "text-embedding-3-small" else normalized

    @field_validator('analytics_activity_outbox_dispatch_cooldown_seconds', mode='before')
    @classmethod
    def validate_analytics_activity_outbox_dispatch_cooldown_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 2
        return max(0, value)

    @field_validator('analytics_assistant_turn_outbox_dispatch_cooldown_seconds', mode='before')
    @classmethod
    def validate_analytics_assistant_turn_outbox_dispatch_cooldown_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 2
        return max(0, value)

    @field_validator('analytics_model_usage_outbox_dispatch_cooldown_seconds', mode='before')
    @classmethod
    def validate_analytics_model_usage_outbox_dispatch_cooldown_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 2
        return max(0, value)

    @field_validator('analytics_outbox_max_retries', mode='before')
    @classmethod
    def validate_analytics_outbox_max_retries(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 25
        return max(1, value)

    @field_validator('analytics_outbox_cleanup_batch_size', mode='before')
    @classmethod
    def validate_analytics_outbox_cleanup_batch_size(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 1000
        return max(1, value)

    @field_validator('analytics_outbox_cleanup_retention_days', mode='before')
    @classmethod
    def validate_analytics_outbox_cleanup_retention_days(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 14
        return max(1, value)

    @field_validator('analytics_outbox_cleanup_beat_interval_seconds', mode='before')
    @classmethod
    def validate_analytics_outbox_cleanup_beat_interval_seconds(cls, v):
        try:
            value = int(v)
        except (TypeError, ValueError):
            return 3600
        return max(60, value)

    # Local file storage
    local_storage_path: str = "/app/data/storage"
    auto_seed_builtin_skills: bool = True
    
    # File upload limits
    max_file_size: int = 200 * 1024 * 1024  # 200MB
    allowed_file_types: list = []  # Populated from file_types.py
    file_chunk_max_length: int = 50_000  # Maximum characters returned per chunk

    @field_validator('allowed_file_types', mode='before')
    @classmethod
    def set_allowed_file_types(cls, v):
        """Use centralized file types from file_types.py."""
        if not v:
            return get_allowed_file_types_list()
        return v

    # Title generation settings
    title_generation_model: str = "gpt-4.1-nano"
    title_generation_max_tokens: int = 50

    # History loading limits (to avoid loading full conversations unnecessarily)
    history_max_messages: int = 120  # load last N messages when preparing provider history

    # Stream timeout for provider updates. Set <= 0 to disable timeout.
    stream_timeout_seconds: int = 3600

    # Embedded image caps when attaching document images directly to prompts
    embedded_images_max_per_document: int = 8
    embedded_images_global_max: int = 24

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields from .env file
    )

    @model_validator(mode="after")
    def validate_required_settings(self) -> "Settings":
        """Fail-fast on missing or insecure configuration."""
        missing_fields: List[str] = []

        if not self.database_url or not self.database_url.strip():
            self.database_url = build_dynamic_database_url() or ""
        if not self.database_url or not self.database_url.strip():
            missing_fields.append("DATABASE_URL")

        if not self.redis_url or not self.redis_url.strip():
            self.redis_url = build_dynamic_redis_url() or ""

        if not self.sandbox_url or not self.sandbox_url.strip():
            self.sandbox_url = build_dynamic_sandbox_url() or ""

        secret = (self.secret_key or "").strip()
        if not secret:
            missing_fields.append("SECRET_KEY")
        elif len(secret) < 32:
            raise SettingsValidationError("SECRET_KEY must be at least 32 characters long for JWT signing security.")

        if self.frontend_url:
            self.frontend_url = self.frontend_url.rstrip("/")

        if self.api_base_url:
            self.api_base_url = self.api_base_url.rstrip("/")

        if missing_fields:
            joined = ", ".join(missing_fields)
            raise SettingsValidationError(
                f"Missing required configuration values: {joined}. Update your environment variables before starting the service."
            )

        return self

    def resolve_frontend_url(self, request_origin: Optional[str] = None) -> str:
        explicit = (self.frontend_url or "").strip().rstrip("/")
        if explicit:
            return explicit

        request_origin_clean = (request_origin or "").strip().rstrip("/")
        if request_origin_clean:
            return request_origin_clean

        runtime_url = get_reserved_service_url("frontend")
        if runtime_url:
            return runtime_url.rstrip("/")

        raise SettingsValidationError(
            "Unable to resolve the frontend URL. Start the frontend with `npm run dev` or set FRONTEND_URL explicitly."
        )

    def resolve_api_base_url(self) -> str:
        explicit = (self.api_base_url or "").strip().rstrip("/")
        if explicit:
            return explicit

        runtime_url = get_reserved_service_url("backend")
        if runtime_url:
            return runtime_url.rstrip("/")

        return ""

# Global settings instance - initialized lazily
_settings_instance = None

def get_settings():
    """Get settings instance, creating it if it doesn't exist"""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance

settings = get_settings()
