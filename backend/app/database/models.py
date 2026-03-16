from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Date,
    ForeignKey,
    Boolean,
    LargeBinary,
    BigInteger,
    Index,
    UniqueConstraint,
    Numeric,
    Enum,
    CheckConstraint,
    and_,
    Computed,
    inspect,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID, TSVECTOR
from sqlalchemy.ext.mutable import MutableDict, MutableList
from typing import Optional
import uuid
from pgvector.sqlalchemy import Vector
from ..config.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    email = Column(CITEXT(), unique=True, index=True, nullable=False)
    name = Column(String(255))
    department = Column(String(255))
    role = Column(String(50), default="user", nullable=False)  # user, admin, etc.
    user_tier = Column(String(20), default="default", nullable=False)  # default, power
    model_override = Column(String(100), nullable=True)  # Optional per-user chat model override
    last_login_at = Column(DateTime(timezone=True))
    last_login_country = Column(String(50))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    conversations = relationship(
        "Conversation",
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="Conversation.user_id",
    )
    files = relationship("File", back_populates="user", cascade="all, delete-orphan", foreign_keys="File.user_id")
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan", foreign_keys="Project.user_id")
    project_memberships = relationship("ProjectMember", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "role IN ('user','admin')",
            name="ck_users_role_valid",
        ),
        CheckConstraint(
            "user_tier IN ('default','power')",
            name="ck_users_user_tier_valid",
        ),
        Index(
            "ix_users_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_where=name.isnot(None),
        ),
    )

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    name = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    custom_instructions = Column(Text, nullable=True)  # AI behavior guidance for this project
    color = Column(String(7), nullable=True)  # Hex color code (e.g., #F7C400)
    archived = Column(Boolean, default=False, nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Relationships
    user = relationship("User", back_populates="projects", foreign_keys=[user_id])
    conversations = relationship("Conversation", back_populates="project", cascade="all, delete-orphan", foreign_keys="Conversation.project_id")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    knowledge_files = relationship(
        "File",
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="File.project_id",
    )
    __table_args__ = (
        CheckConstraint(
            "(NOT archived) OR archived_at IS NOT NULL",
            name="ck_projects_archived_requires_archived_at",
        ),
    )

class ProjectMember(Base):
    __tablename__ = "project_members"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    role = Column(String(20), default="member", nullable=False)  # member, owner
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="project_memberships")

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        CheckConstraint(
            "role IN ('member','owner')",
            name="ck_project_members_role_valid",
        ),
        Index("ix_project_members_project_id", "project_id"),
        Index("ix_project_members_user_id", "user_id"),
    )

class ProjectShare(Base):
    __tablename__ = "project_shares"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False)
    share_token = Column(String(64), unique=True, nullable=False, index=True)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    project = relationship("Project")
    creator = relationship("User")


class Skill(Base):
    """Runtime skill registry row (built-in or custom)."""

    __tablename__ = "skills"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    skill_id = Column(String(120), nullable=False, index=True)
    owner_user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    when_to_use = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="enabled", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    owner = relationship("User", foreign_keys=[owner_user_id])
    files = relationship(
        "SkillFile",
        back_populates="skill",
        cascade="all, delete-orphan",
        foreign_keys="SkillFile.skill_pk_id",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('enabled','disabled')",
            name="ck_skills_status_valid",
        ),
        Index("ix_skills_owner_status", "owner_user_id", "status"),
        Index(
            "uq_skills_global_skill_id",
            "skill_id",
            unique=True,
            postgresql_where=owner_user_id.is_(None),
        ),
        Index(
            "uq_skills_owner_skill_id",
            "owner_user_id",
            "skill_id",
            unique=True,
            postgresql_where=owner_user_id.isnot(None),
        ),
    )


class SkillFile(Base):
    """Materialized skill file content for markdown/modules/assets."""

    __tablename__ = "skill_files"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    skill_pk_id = Column(UUID(as_uuid=False), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False, index=True)
    path = Column(String(1024), nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(40), nullable=False, default="other")
    mime_type = Column(String(255), nullable=False, default="application/octet-stream")
    storage_backend = Column(String(20), nullable=False, default="db")
    blob_path = Column(String(1024), nullable=True)
    text_content = Column(Text, nullable=True)
    binary_content = Column(LargeBinary, nullable=True)
    size_bytes = Column(Integer, nullable=False, default=0)
    checksum_sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    skill = relationship("Skill", back_populates="files", foreign_keys=[skill_pk_id])

    __table_args__ = (
        UniqueConstraint("skill_pk_id", "path", name="uq_skill_files_skill_path"),
        CheckConstraint(
            "category IN ('skill','assets','references','scripts','templates','other')",
            name="ck_skill_files_category_valid",
        ),
        CheckConstraint(
            "storage_backend IN ('db','blob')",
            name="ck_skill_files_storage_backend_valid",
        ),
        CheckConstraint(
            "((storage_backend = 'db' AND blob_path IS NULL AND ((text_content IS NOT NULL) OR (binary_content IS NOT NULL))) OR (storage_backend = 'blob' AND blob_path IS NOT NULL))",
            name="ck_skill_files_content_present",
        ),
        Index("ix_skill_files_skill_category", "skill_pk_id", "category"),
    )

# Constraint name constants — import these instead of hard-coding the strings.
CONSTRAINT_CONVERSATIONS_USER_CREATION_REQUEST = "uq_conversations_user_creation_request"


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=True)
    # Idempotency key for first-message conversation creation.
    # Prevents duplicate conversations when clients retry create/submit requests.
    creation_request_id = Column(String(64), nullable=True)
    # Idempotency key for shared-conversation imports.
    # Prevents duplicate imports for the same user/share token.
    import_source_token = Column(String(64), nullable=True)
    title = Column(String(255), default="New Chat")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    # Track last conversational activity (user/assistant messages) for sidebar ordering
    last_message_at = Column(DateTime(timezone=True), server_default=func.now())
    parent_conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id"), nullable=True)
    branch_from_message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id"), nullable=True)
    conversation_metadata = Column(MutableDict.as_mutable(JSONB), default=dict)
    archived = Column(Boolean, default=False, nullable=False)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    archived_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=True)
    is_pinned = Column(Boolean, default=False, nullable=False, index=True)
    pinned_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="conversations", foreign_keys=[user_id])
    project = relationship("Project", back_populates="conversations", foreign_keys=[project_id])
    files = relationship("File", back_populates="conversation", cascade="all, delete-orphan", foreign_keys="File.conversation_id")
    sector_classification = relationship(
        "ConversationSectorClassification",
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ConversationSectorClassification.conversation_id",
    )
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="Message.conversation_id",
        order_by="Message.created_at",
    )
    runs = relationship(
        "ChatRun",
        back_populates="conversation",
        cascade="all, delete-orphan",
        foreign_keys="ChatRun.conversation_id",
    )
    state = relationship(
        "ConversationState",
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ConversationState.conversation_id",
    )
    run_snapshot = relationship(
        "ChatRunSnapshot",
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ChatRunSnapshot.conversation_id",
    )
    parent_conversation = relationship(
        "Conversation",
        remote_side=[id],
        backref="child_conversations",
        foreign_keys=[parent_conversation_id],
    )
    branch_from_message = relationship("Message", foreign_keys=[branch_from_message_id], post_update=True)
    # Composite indexes for fast list loading and ordering
    __table_args__ = (
        CheckConstraint(
            "(NOT archived) OR archived_at IS NOT NULL",
            name="ck_conversations_archived_requires_archived_at",
        ),
        CheckConstraint(
            "(NOT is_pinned) OR pinned_at IS NOT NULL",
            name="ck_conversations_pinned_requires_pinned_at",
        ),
        # Optimizes: user's conversations filtered by archived and ordered by last_message_at
        Index('ix_conversations_user_archived_last_message', 'user_id', 'archived', last_message_at.desc()),
        # Optimizes: quick lookup by project (sidebar, recent lists)
        Index('ix_conversations_project_archived_last_message', 'project_id', 'archived', last_message_at.desc()),
        # Enforces idempotent conversation creation per user.
        Index(
            CONSTRAINT_CONVERSATIONS_USER_CREATION_REQUEST,
            'user_id',
            'creation_request_id',
            unique=True,
            postgresql_where=creation_request_id.isnot(None),
        ),
        Index(
            'uq_conversations_user_import_source_token',
            'user_id',
            'import_source_token',
            unique=True,
            postgresql_where=import_source_token.isnot(None),
        ),
        Index("ix_conversations_branch_from_message", "branch_from_message_id"),
        Index(
            "ix_conversations_metadata_gin",
            "conversation_metadata",
            postgresql_using="gin",
            postgresql_ops={"conversation_metadata": "jsonb_path_ops"},
        ),
    )


class ConversationSectorClassification(Base):
    """Latest sector classification snapshot for one conversation."""
    __tablename__ = "conversation_sector_classifications"

    conversation_id = Column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sector = Column(String(80), nullable=False, default="unknown", index=True)
    confidence = Column(Numeric(4, 3), nullable=False, default=0)
    user_message_count_at_classification = Column(Integer, nullable=False, default=0)
    classifier_version = Column(String(64), nullable=False, default="sector-v1")
    lock_hits = Column(Integer, nullable=False, default=0)
    is_locked = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="sector_classification")

    __table_args__ = (
        Index(
            "ix_conversation_sector_sector_updated",
            "sector",
            updated_at.desc(),
        ),
    )

class Message(Base):
    """Canonical conversation message row for user and assistant turns."""

    __tablename__ = "messages"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(UUID(as_uuid=False), ForeignKey("chat_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    role = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="completed", index=True)
    text = Column(Text, nullable=False, default="")
    model_provider = Column(String(50), nullable=True)
    model_name = Column(String(120), nullable=True)
    finish_reason = Column(String(40), nullable=True)
    response_latency_ms = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(20, 8), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship("Conversation", back_populates="messages", foreign_keys=[conversation_id])
    run = relationship("ChatRun", back_populates="messages", foreign_keys=[run_id])
    parts = relationship(
        "MessagePart",
        back_populates="message",
        cascade="all, delete-orphan",
        foreign_keys="MessagePart.message_id",
        order_by="MessagePart.ordinal",
    )
    tool_calls = relationship(
        "ToolCall",
        back_populates="message",
        cascade="all, delete-orphan",
        foreign_keys="ToolCall.message_id",
    )
    run_activities = relationship(
        "ChatRunActivity",
        back_populates="message",
        cascade="all, delete-orphan",
        foreign_keys="ChatRunActivity.message_id",
    )

    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system')", name="ck_messages_role_valid"),
        CheckConstraint(
            "status IN ('pending','streaming','paused','completed','failed','cancelled','awaiting_input')",
            name="ck_messages_status_valid",
        ),
        Index("ix_messages_conversation_created", "conversation_id", created_at.asc()),
        Index("ix_messages_conversation_created_id_desc", "conversation_id", created_at.desc(), id.desc()),
        Index("ix_messages_conversation_role_created", "conversation_id", "role", created_at.desc()),
        Index("ix_messages_run_role_created", "run_id", "role", created_at.asc()),
    )


class MessagePart(Base):
    """Structured rendering path for timeline messages."""

    __tablename__ = "message_parts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False, default=0)
    part_type = Column(String(40), nullable=False)
    phase = Column(String(20), nullable=False, default="final")
    text = Column(Text, nullable=True)
    payload_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    message = relationship("Message", back_populates="parts", foreign_keys=[message_id])

    __table_args__ = (
        UniqueConstraint("message_id", "ordinal", name="uq_message_parts_message_ordinal"),
        CheckConstraint(
            "part_type IN ('text','tool_call','tool_result','reasoning','divider','user_input_request','user_input_response','metadata')",
            name="ck_message_parts_part_type_valid",
        ),
        CheckConstraint("phase IN ('worklog','final')", name="ck_message_parts_phase_valid"),
        Index("ix_message_parts_message_part_type", "message_id", "part_type"),
    )


class ToolCall(Base):
    """Operational tool-call log for each assistant turn."""

    __tablename__ = "tool_calls"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=False), ForeignKey("chat_runs.id", ondelete="SET NULL"), nullable=True)
    tool_call_id = Column(String(120), nullable=False)
    tool_name = Column(String(120), nullable=False)
    arguments_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    query_text = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="completed")
    result_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    error_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    message = relationship("Message", back_populates="tool_calls", foreign_keys=[message_id])
    run = relationship("ChatRun", back_populates="tool_calls", foreign_keys=[run_id])

    __table_args__ = (
        UniqueConstraint("message_id", "tool_call_id", name="uq_tool_calls_message_tool_call"),
        Index("ix_tool_calls_run_started", "run_id", started_at.asc()),
        Index("ix_tool_calls_run_call_started", "run_id", "tool_call_id", started_at.desc(), id.desc()),
        Index("ix_tool_calls_name_started", "tool_name", started_at.desc()),
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled')",
            name="ck_tool_calls_status_valid",
        ),
    )


class PendingUserInput(Base):
    """Open user-input requirements emitted by tools such as request_user_input."""

    __tablename__ = "pending_user_inputs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(UUID(as_uuid=False), ForeignKey("chat_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_call_id = Column(String(120), nullable=True)
    request_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run = relationship("ChatRun", back_populates="pending_inputs", foreign_keys=[run_id])
    message = relationship("Message", foreign_keys=[message_id])

    __table_args__ = (
        Index("ix_pending_user_inputs_run_status", "run_id", "status"),
        Index("ix_pending_user_inputs_message_status", "message_id", "status"),
        Index("ix_pending_user_inputs_created_status", created_at.desc(), "status"),
        Index(
            "ix_pending_user_inputs_run_pending_created",
            "run_id",
            created_at.desc(),
            id.desc(),
            postgresql_where=(status == "pending"),
        ),
        Index(
            "ix_pending_user_inputs_run_tool_pending_created",
            "run_id",
            "tool_call_id",
            created_at.desc(),
            id.desc(),
            postgresql_where=(status == "pending"),
        ),
        CheckConstraint(
            "status IN ('pending','resolved','cancelled')",
            name="ck_pending_user_inputs_status_valid",
        ),
    )

class AnalyticsOutbox(Base):
    """Decouples runtime writes from analytics fan-out and aggregation."""

    __tablename__ = "analytics_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(80), nullable=False, index=True)
    event_version = Column(Integer, nullable=False, default=1)
    entity_id = Column(String(64), nullable=False)
    payload_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_analytics_outbox_processed_created", "processed_at", created_at.asc()),
        Index("ix_analytics_outbox_event_created", "event_type", created_at.desc()),
    )


class FactAssistantTurn(Base):
    """Read-optimized assistant turn facts for admin usage analytics."""

    __tablename__ = "fact_assistant_turns"

    message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=False), ForeignKey("chat_runs.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    model_provider = Column(String(50), nullable=True)
    model_name = Column(String(120), nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    reasoning_output_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Numeric(20, 8), nullable=False, default=0)
    latency_ms = Column(Integer, nullable=True)
    tool_call_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        Index("ix_fact_assistant_turns_created", created_at.desc()),
        Index("ix_fact_assistant_turns_user_created", "user_id", created_at.desc()),
        Index("ix_fact_assistant_turns_model_created", "model_provider", "model_name", created_at.desc()),
    )


class FactToolCall(Base):
    """Read-optimized tool-call facts for admin tool analytics."""

    __tablename__ = "fact_tool_calls"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=False), ForeignKey("chat_runs.id", ondelete="SET NULL"), nullable=True)
    tool_name = Column(String(120), nullable=False)
    is_error = Column(Boolean, nullable=False, default=False)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        Index("ix_fact_tool_calls_tool_created", "tool_name", created_at.desc()),
        Index("ix_fact_tool_calls_run_created", "run_id", created_at.asc()),
    )


class FactModelUsageEvent(Base):
    """Read-optimized non-chat model usage facts."""

    __tablename__ = "fact_model_usage_events"

    event_id = Column(String(64), primary_key=True)
    source = Column(String(20), nullable=False, default="non_chat")
    operation_type = Column(String(64), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    model_provider = Column(String(50), nullable=False)
    model_name = Column(String(120), nullable=False)
    call_count = Column(Integer, nullable=False, default=1)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    cache_creation_input_tokens = Column(BigInteger, nullable=False, default=0)
    cache_read_input_tokens = Column(BigInteger, nullable=False, default=0)
    duration_seconds = Column(Numeric(20, 6), nullable=False, default=0)
    latency_ms = Column(Integer, nullable=True)
    cost_usd = Column(Numeric(20, 8), nullable=False, default=0)
    metadata_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)

    __table_args__ = (
        CheckConstraint("source IN ('chat','non_chat')", name="ck_fact_model_usage_events_source_valid"),
        Index("ix_fact_model_usage_events_user_created", "user_id", created_at.desc()),
        Index("ix_fact_model_usage_events_model_created", "model_provider", "model_name", created_at.desc()),
        Index("ix_fact_model_usage_events_source_operation_created", "source", "operation_type", created_at.desc()),
    )


class AggModelUsageDay(Base):
    """Daily model aggregate across chat/non-chat operation sources."""

    __tablename__ = "agg_model_usage_day"

    metric_date = Column(Date, primary_key=True)
    scope = Column(String(20), primary_key=True)
    source = Column(String(20), primary_key=True)
    operation_type = Column(String(64), primary_key=True)
    model_provider = Column(String(50), primary_key=True)
    model_name = Column(String(120), primary_key=True)
    call_count = Column(BigInteger, nullable=False, default=0)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    duration_seconds_sum = Column(Numeric(20, 6), nullable=False, default=0)
    cost_usd = Column(Numeric(20, 8), nullable=False, default=0)
    latency_sum_ms = Column(BigInteger, nullable=False, default=0)
    latency_samples = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_agg_model_usage_day_scope_valid"),
        CheckConstraint("source IN ('chat','non_chat')", name="ck_agg_model_usage_day_source_valid"),
        Index(
            "ix_agg_model_usage_day_scope_source_date",
            "scope",
            "source",
            metric_date.desc(),
        ),
        Index(
            "ix_agg_model_usage_day_scope_model_date",
            "scope",
            "model_provider",
            "model_name",
            metric_date.desc(),
        ),
    )


class AggUsageMinute(Base):
    """Near-real-time minute aggregate for admin dashboard freshness."""

    __tablename__ = "agg_usage_minute"

    bucket_minute = Column(DateTime(timezone=True), primary_key=True)
    scope = Column(String(20), primary_key=True)
    messages_count = Column(Integer, nullable=False, default=0)
    assistant_messages_count = Column(Integer, nullable=False, default=0)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    cost_usd = Column(Numeric(20, 8), nullable=False, default=0)
    latency_sum_ms = Column(BigInteger, nullable=False, default=0)
    latency_samples = Column(Integer, nullable=False, default=0)
    tool_call_count = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_agg_usage_minute_scope_valid"),
    )


class AggUsageDay(Base):
    """Daily aggregate for high-level admin usage dashboards."""

    __tablename__ = "agg_usage_day"

    metric_date = Column(Date, primary_key=True)
    scope = Column(String(20), primary_key=True)
    messages_count = Column(Integer, nullable=False, default=0)
    assistant_messages_count = Column(Integer, nullable=False, default=0)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    cost_usd = Column(Numeric(20, 8), nullable=False, default=0)
    latency_sum_ms = Column(BigInteger, nullable=False, default=0)
    latency_samples = Column(Integer, nullable=False, default=0)
    tool_call_count = Column(BigInteger, nullable=False, default=0)
    active_users = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_agg_usage_day_scope_valid"),
    )


class AggModelDay(Base):
    """Daily model/provider aggregate for admin model analysis."""

    __tablename__ = "agg_model_day"

    metric_date = Column(Date, primary_key=True)
    scope = Column(String(20), primary_key=True)
    model_provider = Column(String(50), primary_key=True)
    model_name = Column(String(120), primary_key=True)
    message_count = Column(Integer, nullable=False, default=0)
    input_tokens = Column(BigInteger, nullable=False, default=0)
    output_tokens = Column(BigInteger, nullable=False, default=0)
    total_tokens = Column(BigInteger, nullable=False, default=0)
    cost_usd = Column(Numeric(20, 8), nullable=False, default=0)
    latency_sum_ms = Column(BigInteger, nullable=False, default=0)
    latency_samples = Column(Integer, nullable=False, default=0)
    tool_call_count = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_agg_model_day_scope_valid"),
    )


class AggToolDay(Base):
    """Daily tool aggregate for admin analytics tool distribution."""

    __tablename__ = "agg_tool_day"

    metric_date = Column(Date, primary_key=True)
    scope = Column(String(20), primary_key=True)
    tool_name = Column(String(120), primary_key=True)
    call_count = Column(BigInteger, nullable=False, default=0)
    error_count = Column(BigInteger, nullable=False, default=0)
    avg_duration_ms = Column(Integer, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_agg_tool_day_scope_valid"),
    )


class AggActivityDay(Base):
    """Daily aggregate for behavioral/admin activity metrics."""

    __tablename__ = "agg_activity_day"

    metric_date = Column(Date, primary_key=True)
    scope = Column(String(20), primary_key=True)
    activity_type = Column(String(64), primary_key=True)
    event_count = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_agg_activity_day_scope_valid"),
        Index("ix_agg_activity_day_scope_type_date", "scope", "activity_type", metric_date.desc()),
    )


class AggFeedbackDay(Base):
    """Daily aggregate for feedback/time-impact admin metrics."""

    __tablename__ = "agg_feedback_day"

    metric_date = Column(Date, primary_key=True)
    scope = Column(String(20), primary_key=True)
    total_count = Column(BigInteger, nullable=False, default=0)
    up_count = Column(BigInteger, nullable=False, default=0)
    down_count = Column(BigInteger, nullable=False, default=0)
    time_saved_minutes = Column(BigInteger, nullable=False, default=0)
    time_spent_minutes = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_agg_feedback_day_scope_valid"),
        Index("ix_agg_feedback_day_scope_date", "scope", metric_date.desc()),
    )


class AdminUserRollup(Base):
    """Per-user admin analytics snapshot for fast users-table sorting/filters."""

    __tablename__ = "admin_user_rollup"

    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    conversation_count = Column(BigInteger, nullable=False, default=0)
    assistant_turn_count = Column(BigInteger, nullable=False, default=0)
    total_cost_usd = Column(Numeric(20, 8), nullable=False, default=0)
    last_assistant_turn_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index("ix_admin_user_rollup_conversation_count", "conversation_count"),
        Index("ix_admin_user_rollup_total_cost_usd", "total_cost_usd"),
        Index("ix_admin_user_rollup_last_turn", last_assistant_turn_at.desc()),
    )


class AdminGlobalSnapshot(Base):
    """Cached global totals for admin usage pages (per scope)."""

    __tablename__ = "admin_global_snapshot"

    scope = Column(String(20), primary_key=True)
    total_users = Column(BigInteger, nullable=False, default=0)
    total_conversations = Column(BigInteger, nullable=False, default=0)
    total_messages = Column(BigInteger, nullable=False, default=0)
    total_files = Column(BigInteger, nullable=False, default=0)
    total_storage_bytes = Column(BigInteger, nullable=False, default=0)
    refreshed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("scope IN ('all','non_admin')", name="ck_admin_global_snapshot_scope_valid"),
        Index("ix_admin_global_snapshot_refreshed", refreshed_at.desc()),
    )


CONSTRAINT_CHAT_RUNS_CONVERSATION_REQUEST = "uq_chat_runs_conversation_request"
CONSTRAINT_CHAT_RUNS_CONVERSATION_USER_MESSAGE = "uq_chat_runs_conversation_user_message"


class ChatRun(Base):
    """Execution lifecycle for one user turn."""

    __tablename__ = "chat_runs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    request_id = Column(String(64), nullable=True)
    status = Column(
        String(20),
        nullable=False,
        default="queued",
        index=True,
    )  # queued | running | paused | completed | failed | cancelled | interrupted
    queued_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    provider_name = Column(String(50), nullable=True)
    model_name = Column(String(120), nullable=True)
    terminal_reason = Column(String(80), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="runs", foreign_keys=[conversation_id])
    user_message = relationship("Message", foreign_keys=[user_message_id], post_update=True)
    messages = relationship("Message", back_populates="run", foreign_keys="Message.run_id")
    tool_calls = relationship("ToolCall", back_populates="run", foreign_keys="ToolCall.run_id")
    activities = relationship(
        "ChatRunActivity",
        back_populates="run",
        cascade="all, delete-orphan",
        foreign_keys="ChatRunActivity.run_id",
    )
    pending_inputs = relationship("PendingUserInput", back_populates="run", foreign_keys="PendingUserInput.run_id")
    snapshot = relationship(
        "ChatRunSnapshot",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ChatRunSnapshot.run_id",
    )
    queued_turn = relationship(
        "ChatRunQueuedTurn",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="ChatRunQueuedTurn.run_id",
    )

    __table_args__ = (
        Index("ix_chat_runs_conversation_started", "conversation_id", queued_at.desc()),
        Index("ix_chat_runs_status_started", "status", queued_at.desc()),
        Index("ix_chat_runs_conversation_status_started", "conversation_id", "status", queued_at.desc()),
        UniqueConstraint("conversation_id", "user_message_id", name=CONSTRAINT_CHAT_RUNS_CONVERSATION_USER_MESSAGE),
        Index(
            CONSTRAINT_CHAT_RUNS_CONVERSATION_REQUEST,
            "conversation_id",
            "request_id",
            unique=True,
            postgresql_where=request_id.isnot(None),
        ),
        CheckConstraint(
            "status IN ('queued','running','paused','completed','failed','cancelled','interrupted')",
            name="ck_chat_runs_status_valid",
        ),
    )


class ConversationState(Base):
    """Latest projection for sidebar/list and fast context usage checks."""

    __tablename__ = "conversation_state"

    conversation_id = Column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_user_message_id = Column(
        UUID(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_assistant_message_id = Column(
        UUID(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    active_run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("chat_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    last_user_preview = Column(String(255), nullable=True)
    awaiting_user_input = Column(Boolean, nullable=False, default=False, index=True)

    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    max_context_tokens = Column(Integer, nullable=True)
    remaining_context_tokens = Column(Integer, nullable=True)
    cumulative_input_tokens = Column(BigInteger, nullable=True)
    cumulative_output_tokens = Column(BigInteger, nullable=True)
    cumulative_total_tokens = Column(BigInteger, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="state", foreign_keys=[conversation_id])
    last_user_message = relationship("Message", foreign_keys=[last_user_message_id], post_update=True)
    last_assistant_message = relationship("Message", foreign_keys=[last_assistant_message_id], post_update=True)
    active_run = relationship("ChatRun", foreign_keys=[active_run_id], post_update=True)

    __table_args__ = ()


class ChatRunSnapshot(Base):
    """Recovery snapshot for the currently active or paused run."""

    __tablename__ = "chat_run_snapshots"

    conversation_id = Column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("chat_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    run_message_id = Column(
        UUID(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assistant_message_id = Column(
        UUID(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(20), nullable=False, default="running", index=True)
    seq = Column(Integer, nullable=False, default=0)
    status_label = Column(String(255), nullable=True)
    draft_text = Column(Text, nullable=False, default="")
    usage_jsonb = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship(
        "Conversation",
        back_populates="run_snapshot",
        foreign_keys=[conversation_id],
    )
    run = relationship("ChatRun", back_populates="snapshot", foreign_keys=[run_id], post_update=True)
    run_message = relationship("Message", foreign_keys=[run_message_id], post_update=True)
    assistant_message = relationship("Message", foreign_keys=[assistant_message_id], post_update=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('running','paused')",
            name="ck_chat_run_snapshots_status_valid",
        ),
        Index(
            "ix_chat_run_snapshots_status_updated",
            "status",
            updated_at.desc(),
        ),
    )


class ChatRunActivity(Base):
    """Durable per-run activity projection used by recovery and settled timeline rendering."""

    __tablename__ = "chat_run_activities"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("chat_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = Column(
        UUID(as_uuid=False),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    item_key = Column(String(160), nullable=False)
    kind = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False, default="running")
    title = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)
    sequence = Column(Integer, nullable=False, default=0)
    payload_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    run = relationship("ChatRun", back_populates="activities", foreign_keys=[run_id])
    message = relationship("Message", back_populates="run_activities", foreign_keys=[message_id])

    __table_args__ = (
        UniqueConstraint("run_id", "item_key", name="uq_chat_run_activities_run_item_key"),
        CheckConstraint(
            "kind IN ('tool','reasoning','compaction','user_input')",
            name="ck_chat_run_activities_kind_valid",
        ),
        CheckConstraint(
            "status IN ('pending','running','completed','failed','cancelled','info')",
            name="ck_chat_run_activities_status_valid",
        ),
        Index(
            "ix_chat_run_activities_run_sequence",
            "run_id",
            "sequence",
            created_at.asc(),
        ),
        Index(
            "ix_chat_run_activities_message_sequence",
            "message_id",
            "sequence",
            created_at.asc(),
        ),
        Index(
            "ix_chat_run_activities_conversation_created",
            "conversation_id",
            created_at.desc(),
        ),
    )


class ChatRunQueuedTurn(Base):
    """Queued follow-up user turn for a conversation while another run is active."""

    __tablename__ = "chat_run_queued_turns"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("chat_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_message_id = Column(
        UUID(as_uuid=False),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    blocked_by_run_id = Column(
        UUID(as_uuid=False),
        ForeignKey("chat_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(20), nullable=False, default="queued")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship("Conversation", foreign_keys=[conversation_id])
    run = relationship("ChatRun", back_populates="queued_turn", foreign_keys=[run_id])
    user_message = relationship("Message", foreign_keys=[user_message_id])
    blocked_by_run = relationship("ChatRun", foreign_keys=[blocked_by_run_id], post_update=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','promoted','cancelled')",
            name="ck_chat_run_queued_turns_status_valid",
        ),
        Index(
            "ix_chat_run_queued_turns_conversation_created",
            "conversation_id",
            "status",
            created_at.desc(),
        ),
    )


class MessageFeedback(Base):
    """Thumb feedback linked to assistant final events."""

    __tablename__ = "message_feedbacks"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    message_id = Column(UUID(as_uuid=False), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    rating = Column(String(4), nullable=False)  # up | down

    time_saved_minutes = Column(Integer, nullable=True)
    improvement_notes = Column(Text, nullable=True)
    issue_description = Column(Text, nullable=True)
    time_spent_minutes = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    message = relationship("Message")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("message_id", "user_id", name="uq_message_feedback_message_user"),
        CheckConstraint(
            "rating IN ('up','down')",
            name="ck_message_feedbacks_rating_valid",
        ),
        Index("ix_message_feedbacks_message_id", "message_id"),
        Index("ix_message_feedbacks_user_id", "user_id"),
    )


class BlobObject(Base):
    __tablename__ = "blob_objects"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    storage_key = Column(String(255), nullable=False, unique=True)
    blob_url = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    purged_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_blob_objects_storage_key", "storage_key", unique=True),
        Index("ix_blob_objects_created_at", created_at.desc()),
        Index("ix_blob_objects_purged_at", purged_at.desc()),
    )


class File(Base):
    __tablename__ = "files"
    
    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id"), nullable=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=True)
    
    # Storage reference
    blob_object_id = Column(UUID(as_uuid=False), ForeignKey("blob_objects.id"), nullable=False, index=True)

    # File metadata
    original_filename = Column(String(255), nullable=False)  # User's original filename
    file_type = Column(String(50), nullable=False)  # pdf, docx, xlsx, txt, etc.
    file_size = Column(BigInteger, nullable=False)  # File size in bytes
    content_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hash for deduplication

    # Processing status for background file processing
    # pending = uploaded but not yet processed, processing = currently being parsed,
    # completed = successfully processed, failed = processing failed
    processing_status = Column(String(20), default="completed", nullable=False, index=True)
    indexed_chunk_count = Column(Integer, nullable=False, default=0)
    indexed_at = Column(DateTime(timezone=True), nullable=True)
    processing_error = Column(Text, nullable=True)

    # Parent-child relationship for embedded images extracted from documents
    parent_file_id = Column(UUID(as_uuid=False), ForeignKey("files.id"), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="files", foreign_keys=[user_id])
    conversation = relationship("Conversation", back_populates="files", foreign_keys=[conversation_id])
    project = relationship("Project", back_populates="knowledge_files", foreign_keys=[project_id])
    blob_object = relationship("BlobObject", foreign_keys=[blob_object_id], lazy="selectin")
    # Parent document containing embedded images, and child images extracted from this document
    parent_file = relationship("File", remote_side=[id], backref="child_images", foreign_keys=[parent_file_id])
    text_content = relationship(
        "FileText",
        back_populates="file",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="FileText.file_id",
    )
    project_chunks = relationship(
        "ProjectFileChunk",
        back_populates="file",
        cascade="all, delete-orphan",
        foreign_keys="ProjectFileChunk.file_id",
    )
    # Common access patterns for attachments/knowledge
    __table_args__ = (
        CheckConstraint(
            "(conversation_id IS NOT NULL AND project_id IS NULL) OR (conversation_id IS NULL AND project_id IS NOT NULL)",
            name="ck_files_exactly_one_scope",
        ),
        CheckConstraint(
            "processing_status IN ('pending','processing','completed','failed')",
            name="ck_files_processing_status_valid",
        ),
        Index('ix_files_conversation', 'conversation_id'),
        Index('ix_files_project_parent', 'project_id', 'parent_file_id'),
        Index('ix_files_project_parent_created_desc', 'project_id', 'parent_file_id', created_at.desc()),
        Index(
            "uq_files_conversation_hash_top_level",
            "conversation_id",
            "content_hash",
            unique=True,
            postgresql_where=and_(
                conversation_id.isnot(None),
                parent_file_id.is_(None),
            ),
        ),
        Index(
            "uq_files_project_hash_top_level",
            "project_id",
            "content_hash",
            unique=True,
            postgresql_where=and_(
                project_id.isnot(None),
                parent_file_id.is_(None),
            ),
        ),
        # Optimizes dedup checks scoped by user/project with most-recent-first retrieval.
        Index('ix_files_hash_user_created', 'content_hash', 'user_id', created_at.desc()),
        Index('ix_files_hash_project_created', 'content_hash', 'project_id', created_at.desc()),
        Index(
            "ix_files_original_filename_trgm",
            "original_filename",
            postgresql_using="gin",
            postgresql_ops={"original_filename": "gin_trgm_ops"},
        ),
    )

    @property
    def filename(self) -> str:
        state = inspect(self)
        if "blob_object" in state.unloaded:
            return ""
        blob = self.__dict__.get("blob_object")
        if getattr(blob, "purged_at", None) is not None:
            return ""
        return str(getattr(blob, "storage_key", "") or "")

    @property
    def blob_url(self) -> str:
        state = inspect(self)
        if "blob_object" in state.unloaded:
            return ""
        blob = self.__dict__.get("blob_object")
        if getattr(blob, "purged_at", None) is not None:
            return ""
        return str(getattr(blob, "blob_url", "") or "")

    @property
    def extracted_text(self) -> Optional[str]:
        state = inspect(self)
        if "text_content" in state.unloaded:
            return None
        text_row = self.__dict__.get("text_content")
        value = getattr(text_row, "extracted_text", None)
        return value if isinstance(value, str) and value else None

    @extracted_text.setter
    def extracted_text(self, value: Optional[str]) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            self.text_content = None
            return
        text_row = getattr(self, "text_content", None)
        if text_row is None:
            text_row = FileText(
                extracted_text=normalized,
                char_count=len(normalized),
            )
            self.text_content = text_row
        else:
            text_row.extracted_text = normalized
            text_row.char_count = len(normalized)


class FileText(Base):
    __tablename__ = "file_texts"

    file_id = Column(
        UUID(as_uuid=False),
        ForeignKey("files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    extracted_text = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=False, default=0)
    extracted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    file = relationship("File", back_populates="text_content", foreign_keys=[file_id])

    __table_args__ = (
        Index(
            "ix_file_texts_extracted_text_trgm",
            "extracted_text",
            postgresql_using="gin",
            postgresql_ops={"extracted_text": "gin_trgm_ops"},
        ),
    )


class ProjectFileChunk(Base):
    __tablename__ = "project_file_chunks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_id = Column(UUID(as_uuid=False), ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)
    chunk_text = Column(Text, nullable=False)
    chunk_tsv = Column(
        TSVECTOR,
        Computed("to_tsvector('english'::regconfig, coalesce(chunk_text, ''))", persisted=True),
        nullable=True,
    )
    embedding = Column(Vector(1536), nullable=False)
    embedding_model = Column(String(80), nullable=False, default="text-embedding-3-small")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    file = relationship("File", back_populates="project_chunks", foreign_keys=[file_id])
    project = relationship("Project", foreign_keys=[project_id])

    __table_args__ = (
        UniqueConstraint("file_id", "chunk_index", name="uq_project_file_chunks_file_chunk_index"),
        CheckConstraint("char_start >= 0", name="ck_project_file_chunks_char_start_non_negative"),
        CheckConstraint("char_end >= char_start", name="ck_project_file_chunks_char_range_valid"),
        Index("ix_project_file_chunks_project_file_chunk", "project_id", "file_id", "chunk_index"),
        Index("ix_project_file_chunks_project_id", "project_id"),
        Index("ix_project_file_chunks_chunk_tsv", "chunk_tsv", postgresql_using="gin"),
        Index(
            "ix_project_file_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
            postgresql_with={"m": 16, "ef_construction": 64},
        ),
    )


class ProjectFileIndexOutbox(Base):
    __tablename__ = "project_file_index_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(80), nullable=False, index=True)
    event_version = Column(Integer, nullable=False, default=1)
    file_id = Column(UUID(as_uuid=False), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    payload_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    file = relationship("File", foreign_keys=[file_id])
    project = relationship("Project", foreign_keys=[project_id])

    __table_args__ = (
        Index("ix_project_file_index_outbox_processed_created", "processed_at", created_at.asc()),
        Index("ix_project_file_index_outbox_event_created", "event_type", created_at.desc()),
    )


class ProjectArchiveJob(Base):
    __tablename__ = "project_archive_jobs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    total_files = Column(Integer, nullable=False, default=0)
    included_files = Column(Integer, nullable=False, default=0)
    skipped_files = Column(Integer, nullable=False, default=0)
    archive_filename = Column(String(255), nullable=True)
    storage_key = Column(String(255), nullable=True)
    blob_url = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)

    project = relationship("Project", foreign_keys=[project_id])
    user = relationship("User", foreign_keys=[requested_by])

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','completed','failed')",
            name="ck_project_archive_jobs_status_valid",
        ),
        Index("ix_project_archive_jobs_project_created", "project_id", created_at.desc()),
        Index("ix_project_archive_jobs_requester_created", "requested_by", created_at.desc()),
    )


class ProjectArchiveOutbox(Base):
    __tablename__ = "project_archive_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(80), nullable=False, index=True)
    event_version = Column(Integer, nullable=False, default=1)
    archive_job_id = Column(
        UUID(as_uuid=False),
        ForeignKey("project_archive_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    payload_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    archive_job = relationship("ProjectArchiveJob", foreign_keys=[archive_job_id])
    project = relationship("Project", foreign_keys=[project_id])

    __table_args__ = (
        Index("ix_project_archive_outbox_processed_created", "processed_at", created_at.asc()),
        Index("ix_project_archive_outbox_event_created", "event_type", created_at.desc()),
    )


# Database indexes for optimal query performance with 500+ users
# (conversation event store + attachments + projects).

# Additional single-column indexes for edge cases
Index('ix_files_created_at', File.created_at)
Index('ix_files_project_id', File.project_id)
# Note: parent_file_id index is already created via index=True on the column
Index('ix_conversations_last_message_at', Conversation.last_message_at)
Index('ix_conversations_archived', Conversation.archived)
Index('ix_conversations_archived_at', Conversation.archived_at)
Index('ix_conversations_project_id', Conversation.project_id)
Index('ix_projects_archived', Project.archived)
Index('ix_projects_archived_at', Project.archived_at)
Index('ix_project_shares_project_id', ProjectShare.project_id)


class StagedFile(Base):
    __tablename__ = "staged_files"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)

    # Optional grouping key for drafts (future use)
    draft_id = Column(String(64), nullable=True, index=True)

    # Storage reference
    blob_object_id = Column(UUID(as_uuid=False), ForeignKey("blob_objects.id"), nullable=False, index=True)

    # File metadata
    original_filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)

    processing_status = Column(String(20), nullable=False, default="pending", index=True)
    processing_error = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    redaction_requested = Column(Boolean, nullable=False, default=False)
    redaction_applied = Column(Boolean, nullable=False, default=False)
    redacted_categories_jsonb = Column(MutableList.as_mutable(JSONB), nullable=False, default=list)

    # Parent-child relationship for embedded images extracted from documents
    parent_staged_id = Column(UUID(as_uuid=False), ForeignKey("staged_files.id"), nullable=True, index=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User")
    blob_object = relationship("BlobObject", foreign_keys=[blob_object_id], lazy="selectin")
    # Parent document containing embedded images, and child images extracted from this document
    parent_staged = relationship("StagedFile", remote_side=[id], backref="child_images", foreign_keys=[parent_staged_id])
    text_content = relationship(
        "StagedFileText",
        back_populates="staged_file",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="StagedFileText.staged_file_id",
    )

    __table_args__ = (
        CheckConstraint(
            "processing_status IN ('pending','processing','completed','failed')",
            name="ck_staged_files_processing_status_valid",
        ),
        Index('ix_staged_files_hash_user_created', 'content_hash', 'user_id', created_at.desc()),
        Index(
            "uq_staged_files_user_hash_top_level",
            "user_id",
            "content_hash",
            unique=True,
            postgresql_where=parent_staged_id.is_(None),
        ),
    )

    @property
    def filename(self) -> str:
        state = inspect(self)
        if "blob_object" in state.unloaded:
            return ""
        blob = self.__dict__.get("blob_object")
        if getattr(blob, "purged_at", None) is not None:
            return ""
        return str(getattr(blob, "storage_key", "") or "")

    @property
    def blob_url(self) -> str:
        state = inspect(self)
        if "blob_object" in state.unloaded:
            return ""
        blob = self.__dict__.get("blob_object")
        if getattr(blob, "purged_at", None) is not None:
            return ""
        return str(getattr(blob, "blob_url", "") or "")

    @property
    def extracted_text(self) -> Optional[str]:
        state = inspect(self)
        if "text_content" in state.unloaded:
            return None
        text_row = self.__dict__.get("text_content")
        value = getattr(text_row, "extracted_text", None)
        return value if isinstance(value, str) and value else None

    @extracted_text.setter
    def extracted_text(self, value: Optional[str]) -> None:
        normalized = str(value or "").strip()
        if not normalized:
            self.text_content = None
            return
        text_row = getattr(self, "text_content", None)
        if text_row is None:
            text_row = StagedFileText(
                extracted_text=normalized,
                char_count=len(normalized),
            )
            self.text_content = text_row
        else:
            text_row.extracted_text = normalized
            text_row.char_count = len(normalized)


class StagedFileText(Base):
    __tablename__ = "staged_file_texts"

    staged_file_id = Column(
        UUID(as_uuid=False),
        ForeignKey("staged_files.id", ondelete="CASCADE"),
        primary_key=True,
    )
    extracted_text = Column(Text, nullable=False)
    char_count = Column(Integer, nullable=False, default=0)
    extracted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    staged_file = relationship("StagedFile", back_populates="text_content", foreign_keys=[staged_file_id])


class StagedFileProcessingOutbox(Base):
    __tablename__ = "staged_file_processing_outbox"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(80), nullable=False, index=True)
    event_version = Column(Integer, nullable=False, default=1)
    staged_file_id = Column(
        UUID(as_uuid=False),
        ForeignKey("staged_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    payload_jsonb = Column(MutableDict.as_mutable(JSONB), default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    processed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    retry_count = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)

    staged_file = relationship("StagedFile", foreign_keys=[staged_file_id])
    user = relationship("User", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_staged_file_processing_outbox_processed_created", "processed_at", created_at.asc()),
        Index("ix_staged_file_processing_outbox_event_created", "event_type", created_at.desc()),
    )

Index('ix_staged_files_created_at', StagedFile.created_at)
Index('ix_staged_files_expires_at', StagedFile.expires_at)
# Note: parent_staged_id index is already created via index=True on the column


class BugReport(Base):
    __tablename__ = "bug_reports"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)

    # Snapshot of reporter details at time of submission
    user_email = Column(String(255), nullable=False)
    user_name = Column(String(255), nullable=True)

    # Report content
    title = Column(String(255), nullable=False)
    severity = Column(String(20), nullable=False, default="medium")  # low | medium | high
    description = Column(Text, nullable=False)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    reporter = relationship("User")

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low','medium','high')",
            name="ck_bug_reports_severity_valid",
        ),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), primary_key=True)
    theme = Column(String(10), nullable=True)  # 'light' | 'dark'
    custom_instructions = Column(Text, nullable=True)  # Per-user assistant instructions (up to 2000 chars)
    notification_sound = Column(Boolean, nullable=False, default=True)  # Play sound on job completion
    timezone = Column(String(64), nullable=True)  # IANA timezone (e.g. "Australia/Sydney")
    locale = Column(String(32), nullable=True)  # BCP 47 locale (e.g. "en-AU")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")


class ConversationShare(Base):
    __tablename__ = "conversation_shares"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id"), nullable=False)
    share_token = Column(String(64), unique=True, nullable=False, index=True)
    created_by = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    event_snapshot = Column(MutableDict.as_mutable(JSONB), nullable=True)  # List of message IDs at share creation time

    # Relationships
    conversation = relationship("Conversation")
    creator = relationship("User")

    __table_args__ = (
        Index(
            "ix_conversation_shares_event_snapshot_gin",
            "event_snapshot",
            postgresql_using="gin",
            postgresql_ops={"event_snapshot": "jsonb_path_ops"},
            postgresql_where=event_snapshot.isnot(None),
        ),
    )


class AppSetting(Base):
    """
    Runtime configuration settings stored in database.

    Common setting keys:
    - chat_default_model: Default-tier chat model (`gpt-5.4`)
    - chat_power_model: Power-tier chat model (`gpt-5.4`)
    - code_repository: Source control platform (`github`)
    - code_repository_migrated_at: Optional migration timestamp (ISO format)
    """
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

Index('ix_app_settings_key', AppSetting.key)


class RefreshToken(Base):
    """
    Refresh tokens for secure session management.

    Implements token rotation: each refresh issues a new token and invalidates the old one.
    If a revoked token is reused, all tokens for that user are revoked (theft detection).
    """
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hash of token
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Device/session tracking (optional, for future use)
    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(45), nullable=True)  # IPv6 max length

    user = relationship("User")

    __table_args__ = (
        Index('ix_refresh_tokens_user_revoked', 'user_id', 'revoked'),
        Index('ix_refresh_tokens_expires', 'expires_at'),
    )


# ------------------------------
# Personal Tasks feature models
# ------------------------------

class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    created_by_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    # Free-text categorisation field; not linked to any other table
    category = Column(String(255), nullable=True)
    conversation_id = Column(UUID(as_uuid=False), ForeignKey("conversations.id"), nullable=True)

    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="todo")  # todo | in_progress | done
    priority = Column(String(10), nullable=False, default="medium")  # low | medium | high | urgent

    due_at = Column(Date, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    is_archived = Column(Boolean, default=False, nullable=False, index=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    owner = relationship("User", foreign_keys=[created_by_id])
    conversation = relationship("Conversation", foreign_keys=[conversation_id])
    assignments = relationship(
        "TaskAssignment",
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="TaskAssignment.task_id",
    )
    comments = relationship(
        "TaskComment",
        back_populates="task",
        cascade="all, delete-orphan",
        foreign_keys="TaskComment.task_id",
    )

    @property
    def assignees(self):
        return self.assignments or []

    __table_args__ = (
        CheckConstraint(
            "status IN ('todo','in_progress','done')",
            name="ck_tasks_status_valid",
        ),
        CheckConstraint(
            "priority IN ('low','medium','high','urgent')",
            name="ck_tasks_priority_valid",
        ),
        CheckConstraint(
            "(NOT is_archived) OR archived_at IS NOT NULL",
            name="ck_tasks_archived_requires_archived_at",
        ),
        Index(
            'ix_tasks_owner_status_due',
            'created_by_id', 'status', 'due_at',
            postgresql_where=(is_archived == False),
        ),
        Index('ix_tasks_owner_created', 'created_by_id', created_at.desc()),
        Index(
            'ix_tasks_category_status_due',
            'category', 'status', 'due_at',
            postgresql_where=(is_archived == False),
        ),
        Index('ix_tasks_conversation_created', 'conversation_id', 'created_at'),
    )


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    task_id = Column(UUID(as_uuid=False), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    task = relationship("Task", back_populates="comments")
    user = relationship("User")

    @property
    def user_name(self):
        if not self.user:
            return None
        return self.user.name or self.user.email

    @property
    def user_email(self):
        if not self.user:
            return None
        return self.user.email

    __table_args__ = (
        Index('ix_task_comments_task_created', 'task_id', 'created_at'),
    )


class TaskAssignment(Base):
    __tablename__ = "task_assignments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    task_id = Column(UUID(as_uuid=False), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    assigned_by_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False, index=True)
    seen_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("Task", back_populates="assignments", foreign_keys=[task_id])
    assignee = relationship("User", foreign_keys=[user_id])
    assigned_by = relationship("User", foreign_keys=[assigned_by_id])

    @property
    def user_name(self):
        if not self.assignee:
            return None
        return self.assignee.name or self.assignee.email

    @property
    def user_email(self):
        if not self.assignee:
            return None
        return self.assignee.email

    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_task_assignment_task_user"),
        Index("ix_task_assignments_user_task", "user_id", "task_id"),
        Index("ix_task_assignments_task_user", "task_id", "user_id"),
        Index("ix_task_assignments_user_seen", "user_id", "seen_at"),
    )


# ------------------------------
# User Redaction List feature
# ------------------------------

class UserRedactionEntry(Base):
    """
    User-specific names/terms to redact from uploaded files.

    Pattern matching catches variations like all caps, initials,
    spaced letters, reversed name order, etc.
    """
    __tablename__ = "user_redaction_entries"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # The name/term to redact
    is_active = Column(Boolean, default=True, nullable=False)   # Toggle without deleting
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User")

    __table_args__ = (
        Index('ix_user_redaction_entries_user_active', 'user_id', 'is_active'),
    )


# ------------------------------
# User Activity Tracking (Behavioral Metrics)
# ------------------------------

class UserActivity(Base):
    """
    Generic activity log for tracking user actions.

    Used for behavioral metrics (AI Capability Framework):
    - share_imported: User imported a shared conversation
    - conversation_branched: User branched a conversation
    - conversation_compacted: User compacted a conversation
    - group_joined: User joined a project
    - redaction_applied: Redaction was applied to a file

    Links to source records via target_id for detailed queries.
    Stores high-value dimensions as typed nullable columns for scalable
    filtering/joins/rollups, while keeping optional metadata flexible.
    Aggregate counters are derived via fact/agg tables.
    """
    __tablename__ = "user_activity"

    id = Column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_type = Column(String(50), nullable=False)
    target_id = Column(UUID(as_uuid=False), nullable=False)  # ID of the thing acted on (share, conversation, etc.)
    conversation_id = Column(UUID(as_uuid=False), nullable=True)
    project_id = Column(UUID(as_uuid=False), nullable=True)
    task_id = Column(UUID(as_uuid=False), nullable=True)
    run_id = Column(UUID(as_uuid=False), nullable=True)
    metadata_jsonb = Column(MutableDict.as_mutable(JSONB), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User")

    __table_args__ = (
        Index("ix_user_activity_user_type", "user_id", "activity_type"),
        Index("ix_user_activity_type_created", "activity_type", "created_at"),
        Index("ix_user_activity_type_created_user", "activity_type", "created_at", "user_id"),
        Index("ix_user_activity_target", "target_id"),
        Index(
            "ix_user_activity_conversation_created",
            "conversation_id",
            created_at.desc(),
            postgresql_where=conversation_id.isnot(None),
        ),
        Index(
            "ix_user_activity_project_created",
            "project_id",
            created_at.desc(),
            postgresql_where=project_id.isnot(None),
        ),
        Index(
            "ix_user_activity_task_created",
            "task_id",
            created_at.desc(),
            postgresql_where=task_id.isnot(None),
        ),
        Index(
            "ix_user_activity_run_created",
            "run_id",
            created_at.desc(),
            postgresql_where=run_id.isnot(None),
        ),
    )


class UserLoginDaily(Base):
    """Immutable per-user daily login events for historical active-user analytics."""

    __tablename__ = "user_login_daily"

    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    login_date = Column(Date, primary_key=True)
    first_login_at = Column(DateTime(timezone=True), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index("ix_user_login_daily_login_date", "login_date", "user_id"),
        Index("ix_user_login_daily_user_date", "user_id", login_date.desc()),
    )
