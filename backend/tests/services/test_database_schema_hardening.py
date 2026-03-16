from sqlalchemy import CheckConstraint

from app.database.models import (
    BlobObject,
    BugReport,
    Conversation,
    File,
    MessageFeedback,
    Project,
    ProjectArchiveJob,
    ProjectArchiveOutbox,
    ProjectMember,
    Skill,
    SkillFile,
    StagedFile,
    StagedFileProcessingOutbox,
    Task,
    User,
    UserPreference,
    UserRedactionEntry,
)


def _check_names(table) -> set[str]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name
    }


def _indexes_by_name(table) -> dict[str, object]:
    return {index.name: index for index in table.indexes if index.name}


def test_domain_checks_exist_for_core_mutable_tables() -> None:
    user_checks = _check_names(User.__table__)
    assert "ck_users_role_valid" in user_checks
    assert "ck_users_user_tier_valid" in user_checks

    task_checks = _check_names(Task.__table__)
    assert "ck_tasks_status_valid" in task_checks
    assert "ck_tasks_priority_valid" in task_checks

    file_checks = _check_names(File.__table__)
    assert "ck_files_exactly_one_scope" in file_checks
    assert "ck_files_processing_status_valid" in file_checks

    staged_checks = _check_names(StagedFile.__table__)
    assert "ck_staged_files_processing_status_valid" in staged_checks

    archive_checks = _check_names(ProjectArchiveJob.__table__)
    assert "ck_project_archive_jobs_status_valid" in archive_checks

    feedback_checks = _check_names(MessageFeedback.__table__)
    assert "ck_message_feedbacks_rating_valid" in feedback_checks

    member_checks = _check_names(ProjectMember.__table__)
    assert "ck_project_members_role_valid" in member_checks

    bug_report_checks = _check_names(BugReport.__table__)
    assert "ck_bug_reports_severity_valid" in bug_report_checks

    skill_checks = _check_names(Skill.__table__)
    assert "ck_skills_status_valid" in skill_checks

    skill_file_checks = _check_names(SkillFile.__table__)
    assert "ck_skill_files_category_valid" in skill_file_checks
    assert "ck_skill_files_storage_backend_valid" in skill_file_checks
    assert "ck_skill_files_content_present" in skill_file_checks


def test_boolean_columns_do_not_allow_tristate_null() -> None:
    assert User.__table__.c.is_active.nullable is False
    assert Project.__table__.c.is_public.nullable is False
    assert Project.__table__.c.is_public_candidate.nullable is False
    assert Project.__table__.c.archived.nullable is False
    assert Conversation.__table__.c.archived.nullable is False
    assert Conversation.__table__.c.is_pinned.nullable is False
    assert Task.__table__.c.is_archived.nullable is False
    assert UserPreference.__table__.c.notification_sound.nullable is False
    assert UserRedactionEntry.__table__.c.is_active.nullable is False


def test_file_dedupe_indexes_are_unique_and_partial() -> None:
    blob_indexes = _indexes_by_name(BlobObject.__table__)
    blob_storage_idx = blob_indexes["uq_blob_objects_storage_key"]
    assert blob_storage_idx.unique is True
    assert list(blob_storage_idx.columns.keys()) == ["storage_key"]
    assert "ix_blob_objects_created_at" in blob_indexes
    assert "ix_blob_objects_purged_at" in blob_indexes

    file_indexes = _indexes_by_name(File.__table__)
    assert "uq_files_filename" not in file_indexes
    assert "ix_files_blob_object_id" in file_indexes

    conversation_idx = file_indexes["uq_files_conversation_hash_top_level"]
    assert conversation_idx.unique is True
    assert list(conversation_idx.columns.keys()) == ["conversation_id", "content_hash"]
    conversation_where = str(conversation_idx.dialect_options["postgresql"]["where"])
    assert "conversation_id" in conversation_where
    assert "parent_file_id" in conversation_where

    project_idx = file_indexes["uq_files_project_hash_top_level"]
    assert project_idx.unique is True
    assert list(project_idx.columns.keys()) == ["project_id", "content_hash"]
    project_where = str(project_idx.dialect_options["postgresql"]["where"])
    assert "project_id" in project_where
    assert "parent_file_id" in project_where

    staged_indexes = _indexes_by_name(StagedFile.__table__)
    assert "uq_staged_files_filename" not in staged_indexes
    assert "ix_staged_files_blob_object_id" in staged_indexes
    assert "ix_staged_files_hash_user_created" in staged_indexes
    assert "ix_staged_files_created_at" in staged_indexes
    assert "ix_staged_files_expires_at" in staged_indexes

    staged_idx = staged_indexes["uq_staged_files_user_hash_top_level"]
    assert staged_idx.unique is True
    assert list(staged_idx.columns.keys()) == ["user_id", "content_hash"]
    staged_where = str(staged_idx.dialect_options["postgresql"]["where"])
    assert "parent_staged_id" in staged_where

    archive_job_indexes = _indexes_by_name(ProjectArchiveJob.__table__)
    assert "ix_project_archive_jobs_project_created" in archive_job_indexes
    assert "ix_project_archive_jobs_requester_created" in archive_job_indexes

    archive_outbox_indexes = _indexes_by_name(ProjectArchiveOutbox.__table__)
    assert "ix_project_archive_outbox_processed_created" in archive_outbox_indexes
    assert "ix_project_archive_outbox_event_created" in archive_outbox_indexes

    staged_outbox_indexes = _indexes_by_name(StagedFileProcessingOutbox.__table__)
    assert "ix_staged_file_processing_outbox_processed_created" in staged_outbox_indexes
    assert "ix_staged_file_processing_outbox_event_created" in staged_outbox_indexes


def test_skill_scope_indexes_are_unique_and_partial() -> None:
    skill_indexes = _indexes_by_name(Skill.__table__)

    global_idx = skill_indexes["uq_skills_global_skill_id"]
    assert global_idx.unique is True
    assert list(global_idx.columns.keys()) == ["skill_id"]
    global_where = str(global_idx.dialect_options["postgresql"]["where"])
    assert "owner_user_id" in global_where

    owner_idx = skill_indexes["uq_skills_owner_skill_id"]
    assert owner_idx.unique is True
    assert list(owner_idx.columns.keys()) == ["owner_user_id", "skill_id"]
    owner_where = str(owner_idx.dialect_options["postgresql"]["where"])
    assert "owner_user_id" in owner_where
