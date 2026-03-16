"""Core file service for CRUD operations and queries."""

import hashlib
import logging
import os
import re
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, joinedload, load_only, selectinload

from ...config.settings import settings
from ...database.models import (
    BlobObject,
    Conversation,
    File,
    FileText,
    Project,
    ProjectFileChunk,
    ProjectFileIndexOutbox,
    ProjectMember,
    StagedFile,
    StagedFileText,
    User,
    UserRedactionEntry,
)
from ...logging import log_event
from ..admin import analytics_event_recorder
from .blob_storage_service import blob_storage_service

logger = logging.getLogger(__name__)


class FileService:
    """Core file service handling CRUD operations and queries."""

    def _file_response_query(self, db: Session, *, include_text: bool = False, include_uploader: bool = False):
        query = db.query(File).options(
            selectinload(File.blob_object).load_only(
                BlobObject.storage_key,
                BlobObject.blob_url,
                BlobObject.purged_at,
            ),
        )
        if include_text:
            query = query.options(selectinload(File.text_content))
        if include_uploader:
            query = query.options(joinedload(File.user).load_only(User.id, User.name, User.email))
        return query

    def _staged_file_response_query(self, db: Session, *, include_text: bool = True):
        query = db.query(StagedFile).options(
            selectinload(StagedFile.blob_object).load_only(
                BlobObject.storage_key,
                BlobObject.blob_url,
                BlobObject.purged_at,
            ),
        )
        if include_text:
            query = query.options(selectinload(StagedFile.text_content))
        return query

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_user_redaction_list(self, user_id: str, db: Session) -> List[str]:
        """Fetch active redaction entries for a user."""
        entries = db.query(UserRedactionEntry.name).filter(
            UserRedactionEntry.user_id == user_id,
            UserRedactionEntry.is_active == True,
        ).all()
        return [e[0] for e in entries]

    async def get_user_redaction_list_async(self, user_id: str, db: AsyncSession) -> List[str]:
        """Async fetch of active redaction entries for a user."""
        rows = await db.execute(
            select(UserRedactionEntry.name).where(
                UserRedactionEntry.user_id == user_id,
                UserRedactionEntry.is_active.is_(True),
            )
        )
        return [str(name) for name in rows.scalars().all() if name]

    def generate_filename(self, original_filename: str, user_id: str) -> str:
        """Generate unique filename for storage."""
        file_extension = original_filename.split('.')[-1] if '.' in original_filename else ''
        unique_id = str(uuid.uuid4())
        return f"{user_id}/{unique_id}.{file_extension}" if file_extension else f"{user_id}/{unique_id}"

    def calculate_content_hash(self, content: bytes, *, redacted: bool = False) -> str:
        """Calculate SHA-256 hash of file content."""
        hasher = hashlib.sha256()
        hasher.update(content)
        if redacted:
            hasher.update(b"|redacted")
        return hasher.hexdigest()

    def calculate_content_hash_from_fileobj(
        self,
        file_obj: BinaryIO,
        *,
        redacted: bool = False,
        chunk_size: int = 1024 * 1024,
    ) -> Tuple[str, int]:
        """Stream SHA-256 hash from a file-like object and return (hash, size)."""
        hasher = hashlib.sha256()
        total_size = 0
        file_obj.seek(0)
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)
            hasher.update(chunk)
        if redacted:
            hasher.update(b"|redacted")
        file_obj.seek(0)
        return hasher.hexdigest(), total_size

    def _sanitize_archive_filename(self, raw_name: str) -> str:
        """Normalize archive entry names to avoid traversal/invalid-path issues."""
        base_name = (raw_name or "").replace("\\", "/").split("/")[-1].strip()
        if not base_name:
            base_name = "file"
        cleaned = re.sub(r'[\x00-\x1f<>:"|?*]+', "_", base_name).strip(". ")
        return cleaned or "file"

    def _ensure_unique_archive_name(self, raw_name: str, seen_names: set[str]) -> str:
        """De-duplicate filenames so all project files are preserved in the archive."""
        safe_name = self._sanitize_archive_filename(raw_name)
        if safe_name not in seen_names:
            seen_names.add(safe_name)
            return safe_name

        stem, ext = os.path.splitext(safe_name)
        counter = 2
        while True:
            candidate = f"{stem} ({counter}){ext}"
            if candidate not in seen_names:
                seen_names.add(candidate)
                return candidate
            counter += 1

    def _create_blob_object(
        self,
        *,
        db: Session,
        storage_key: str,
        blob_url: str,
    ) -> BlobObject:
        blob_object = BlobObject(
            storage_key=storage_key,
            blob_url=blob_url,
        )
        db.add(blob_object)
        db.flush()
        return blob_object

    def _cleanup_orphan_blob_objects(
        self,
        *,
        db: Session,
        blob_object_ids: List[str],
    ) -> None:
        if not blob_object_ids:
            return

        candidate_ids = {str(blob_id) for blob_id in blob_object_ids if blob_id}
        if not candidate_ids:
            return

        file_refs = {
            str(blob_id)
            for (blob_id,) in (
                db.query(File.blob_object_id)
                .filter(File.blob_object_id.in_(candidate_ids))
                .all()
            )
            if blob_id
        }
        staged_refs = {
            str(blob_id)
            for (blob_id,) in (
                db.query(StagedFile.blob_object_id)
                .filter(StagedFile.blob_object_id.in_(candidate_ids))
                .all()
            )
            if blob_id
        }

        orphan_ids = sorted(candidate_ids - file_refs - staged_refs)
        if not orphan_ids:
            return

        orphan_blobs = (
            db.query(BlobObject)
            .filter(BlobObject.id.in_(orphan_ids))
            .all()
        )
        for blob_row in orphan_blobs:
            storage_key = str(getattr(blob_row, "storage_key", "") or "").strip()
            if storage_key and not blob_storage_service.delete(storage_key):
                continue
            db.delete(blob_row)

    def _purge_blob_objects(
        self,
        *,
        db: Session,
        blob_object_ids: set[str],
        commit: bool,
    ) -> int:
        if not blob_object_ids:
            return 0

        blob_rows = (
            db.query(BlobObject)
            .filter(
                BlobObject.id.in_(sorted(blob_object_ids)),
                BlobObject.purged_at.is_(None),
            )
            .all()
        )
        if not blob_rows:
            return 0

        now = datetime.now(timezone.utc)
        purged_count = 0
        for blob_row in blob_rows:
            storage_key = str(getattr(blob_row, "storage_key", "") or "").strip()
            if storage_key and not blob_storage_service.delete(storage_key):
                continue
            blob_row.purged_at = now
            purged_count += 1

        if commit and purged_count > 0:
            db.commit()

        return purged_count

    def purge_archived_conversation_blob_content(
        self,
        *,
        db: Session,
        conversation_ids: List[str],
        commit: bool = True,
    ) -> int:
        """Delete blob bytes for archived conversations while preserving DB metadata rows.

        Blob content is purged only when there are no active references from:
        - non-archived conversation files,
        - project knowledge files,
        - staged files.
        """
        if not conversation_ids:
            return 0

        target_conversation_ids = {str(cid) for cid in conversation_ids if cid}
        if not target_conversation_ids:
            return 0

        candidate_blob_ids = {
            str(blob_id)
            for (blob_id,) in (
                db.query(File.blob_object_id)
                .join(Conversation, Conversation.id == File.conversation_id)
                .filter(
                    Conversation.id.in_(target_conversation_ids),
                    Conversation.archived.is_(True),
                    File.blob_object_id.isnot(None),
                )
                .all()
            )
            if blob_id
        }
        if not candidate_blob_ids:
            return 0

        active_conversation_refs = {
            str(blob_id)
            for (blob_id,) in (
                db.query(File.blob_object_id)
                .join(Conversation, Conversation.id == File.conversation_id)
                .filter(
                    File.blob_object_id.in_(candidate_blob_ids),
                    Conversation.archived.is_(False),
                )
                .all()
            )
            if blob_id
        }
        project_refs = {
            str(blob_id)
            for (blob_id,) in (
                db.query(File.blob_object_id)
                .filter(
                    File.blob_object_id.in_(candidate_blob_ids),
                    File.project_id.isnot(None),
                )
                .all()
            )
            if blob_id
        }
        staged_refs = {
            str(blob_id)
            for (blob_id,) in (
                db.query(StagedFile.blob_object_id)
                .filter(StagedFile.blob_object_id.in_(candidate_blob_ids))
                .all()
            )
            if blob_id
        }

        purge_ids = candidate_blob_ids - active_conversation_refs - project_refs - staged_refs
        return self._purge_blob_objects(
            db=db,
            blob_object_ids=purge_ids,
            commit=commit,
        )

    def purge_archived_project_blob_content(
        self,
        *,
        db: Session,
        project_ids: List[str],
        commit: bool = True,
    ) -> int:
        """Delete blob bytes for archived projects while preserving DB metadata rows.

        This covers both project knowledge files and archived conversation files in
        the archived project scope. Blobs still referenced by active/out-of-scope
        files or staged files are not purged.
        """
        if not project_ids:
            return 0

        target_project_ids = {str(pid) for pid in project_ids if pid}
        if not target_project_ids:
            return 0

        target_conversation_ids = {
            str(conversation_id)
            for (conversation_id,) in (
                db.query(Conversation.id)
                .filter(
                    Conversation.project_id.in_(target_project_ids),
                    Conversation.archived.is_(True),
                )
                .all()
            )
            if conversation_id
        }

        project_blob_ids = {
            str(blob_id)
            for (blob_id,) in (
                db.query(File.blob_object_id)
                .join(Project, Project.id == File.project_id)
                .filter(
                    Project.id.in_(target_project_ids),
                    Project.archived.is_(True),
                    File.blob_object_id.isnot(None),
                )
                .all()
            )
            if blob_id
        }
        conversation_blob_ids = {
            str(blob_id)
            for (blob_id,) in (
                db.query(File.blob_object_id)
                .join(Conversation, Conversation.id == File.conversation_id)
                .filter(
                    Conversation.id.in_(target_conversation_ids),
                    Conversation.archived.is_(True),
                    File.blob_object_id.isnot(None),
                )
                .all()
            )
            if blob_id
        }
        candidate_blob_ids = project_blob_ids | conversation_blob_ids
        if not candidate_blob_ids:
            return 0

        blocking_file_refs = {
            str(blob_id)
            for (blob_id,) in (
                db.query(File.blob_object_id)
                .outerjoin(Project, Project.id == File.project_id)
                .outerjoin(Conversation, Conversation.id == File.conversation_id)
                .filter(
                    File.blob_object_id.in_(candidate_blob_ids),
                    or_(
                        and_(
                            File.project_id.isnot(None),
                            or_(
                                Project.archived.is_(False),
                                ~Project.id.in_(target_project_ids),
                            ),
                        ),
                        and_(
                            File.conversation_id.isnot(None),
                            or_(
                                Conversation.archived.is_(False),
                                ~Conversation.id.in_(target_conversation_ids),
                            ),
                        ),
                    ),
                )
                .all()
            )
            if blob_id
        }

        staged_refs = {
            str(blob_id)
            for (blob_id,) in (
                db.query(StagedFile.blob_object_id)
                .filter(StagedFile.blob_object_id.in_(candidate_blob_ids))
                .all()
            )
            if blob_id
        }

        purge_ids = candidate_blob_ids - blocking_file_refs - staged_refs
        return self._purge_blob_objects(
            db=db,
            blob_object_ids=purge_ids,
            commit=commit,
        )

    def purge_archived_conversation_blob_content_best_effort(
        self,
        *,
        db: Session,
        conversation_ids: List[str],
        user_id: Optional[str] = None,
    ) -> int:
        if not conversation_ids:
            return 0

        try:
            purged_blob_count = self.purge_archived_conversation_blob_content(
                db=db,
                conversation_ids=conversation_ids,
                commit=True,
            )
            if purged_blob_count > 0:
                log_event(
                    logger,
                    "INFO",
                    "chat.archive.blob_content_purged",
                    "timing",
                    user_id=user_id,
                    conversation_count=len(conversation_ids),
                    purged_blob_count=purged_blob_count,
                )
            return purged_blob_count
        except Exception as exc:
            db.rollback()
            log_event(
                logger,
                "WARNING",
                "chat.archive.blob_content_purge_failed",
                "retry",
                user_id=user_id,
                conversation_count=len(conversation_ids),
                exc_info=exc,
            )
            return 0

    def purge_archived_project_blob_content_best_effort(
        self,
        *,
        db: Session,
        project_ids: List[str],
        user_id: Optional[str] = None,
    ) -> int:
        if not project_ids:
            return 0

        try:
            purged_blob_count = self.purge_archived_project_blob_content(
                db=db,
                project_ids=project_ids,
                commit=True,
            )
            if purged_blob_count > 0:
                log_event(
                    logger,
                    "INFO",
                    "projects.archive.blob_content_purged",
                    "timing",
                    user_id=user_id,
                    project_count=len(project_ids),
                    project_ids=project_ids[:5],
                    purged_blob_count=purged_blob_count,
                )
            return purged_blob_count
        except Exception as exc:
            db.rollback()
            log_event(
                logger,
                "WARNING",
                "projects.archive.blob_content_purge_failed",
                "retry",
                user_id=user_id,
                project_count=len(project_ids),
                project_ids=project_ids[:5],
                exc_info=exc,
            )
            return 0

    # =========================================================================
    # Duplicate Checking
    # =========================================================================

    def check_duplicate_file(
        self, *, content_hash: str, db: Session,
        user_id: Optional[str] = None, project_id: Optional[str] = None,
    ) -> Optional[File]:
        """Check if a file with the same content already exists."""
        query = self._file_response_query(
            db,
            include_text=True,
            include_uploader=bool(project_id),
        ).filter(
            File.content_hash == content_hash,
            File.parent_file_id.is_(None),
        )
        if project_id:
            query = query.filter(File.project_id == project_id)
        elif user_id:
            query = query.filter(File.user_id == user_id)
        else:
            return None
        return query.order_by(File.created_at.desc()).first()

    async def check_duplicate_file_async(
        self,
        *,
        content_hash: str,
        db: AsyncSession,
        user_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[File]:
        """Async check for duplicate top-level files."""
        stmt = (
            select(File)
            .options(
                selectinload(File.blob_object).load_only(
                    BlobObject.storage_key,
                    BlobObject.blob_url,
                    BlobObject.purged_at,
                ),
                selectinload(File.text_content),
            )
            .where(
                File.content_hash == content_hash,
                File.parent_file_id.is_(None),
            )
            .order_by(File.created_at.desc())
        )
        if project_id:
            stmt = stmt.options(
                joinedload(File.user).load_only(User.id, User.name, User.email)
            ).where(File.project_id == project_id)
        elif user_id:
            stmt = stmt.where(File.user_id == user_id)
        else:
            return None
        return (await db.scalars(stmt)).first()

    def get_scope_file_by_hash(
        self,
        *,
        db: Session,
        content_hash: str,
        conversation_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[File]:
        """Return top-level file in the exact target scope for hash, if present."""
        query = self._file_response_query(
            db,
            include_text=True,
            include_uploader=bool(project_id),
        ).filter(
            File.content_hash == content_hash,
            File.parent_file_id.is_(None),
        )
        if conversation_id:
            query = query.filter(
                File.conversation_id == conversation_id,
                File.project_id.is_(None),
            )
        elif project_id:
            query = query.filter(
                File.project_id == project_id,
                File.conversation_id.is_(None),
            )
        else:
            return None
        return query.order_by(File.created_at.desc()).first()

    async def get_scope_file_by_hash_async(
        self,
        *,
        db: AsyncSession,
        content_hash: str,
        conversation_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[File]:
        """Async fetch of top-level file in the exact target scope for hash."""
        stmt = (
            select(File)
            .options(
                selectinload(File.blob_object).load_only(
                    BlobObject.storage_key,
                    BlobObject.blob_url,
                    BlobObject.purged_at,
                ),
                selectinload(File.text_content),
            )
            .where(
                File.content_hash == content_hash,
                File.parent_file_id.is_(None),
            )
            .order_by(File.created_at.desc())
        )
        if conversation_id:
            stmt = stmt.where(
                File.conversation_id == conversation_id,
                File.project_id.is_(None),
            )
        elif project_id:
            stmt = stmt.options(
                joinedload(File.user).load_only(User.id, User.name, User.email)
            ).where(
                File.project_id == project_id,
                File.conversation_id.is_(None),
            )
        else:
            return None
        return (await db.scalars(stmt)).first()

    def check_duplicate_staged(self, content_hash: str, user_id: str, db: Session) -> Optional[StagedFile]:
        """Check if a staged file with same content already exists for user."""
        return self._staged_file_response_query(db).filter(
            and_(
                StagedFile.content_hash == content_hash,
                StagedFile.user_id == user_id,
                StagedFile.parent_staged_id.is_(None),
            )
        ).order_by(StagedFile.created_at.desc()).first()

    async def check_duplicate_staged_async(
        self,
        content_hash: str,
        user_id: str,
        db: AsyncSession,
    ) -> Optional[StagedFile]:
        """Async check for duplicate top-level staged files."""
        stmt = (
            select(StagedFile)
            .options(
                selectinload(StagedFile.blob_object).load_only(
                    BlobObject.storage_key,
                    BlobObject.blob_url,
                    BlobObject.purged_at,
                ),
                selectinload(StagedFile.text_content),
            )
            .where(
                StagedFile.content_hash == content_hash,
                StagedFile.user_id == user_id,
                StagedFile.parent_staged_id.is_(None),
            )
            .order_by(StagedFile.created_at.desc())
        )
        return (await db.scalars(stmt)).first()

    # =========================================================================
    # File Record CRUD
    # =========================================================================

    def create_file_record(
        self,
        *,
        user_id: str,
        original_filename: str,
        file_type: str,
        file_size: int,
        content_hash: str,
        extracted_text: Optional[str],
        db: Session,
        conversation_id: Optional[str] = None,
        project_id: Optional[str] = None,
        storage_key: Optional[str] = None,
        blob_url: Optional[str] = None,
        blob_object_id: Optional[str] = None,
        commit: bool = False,
        processing_status: str = "completed",
    ) -> File:
        """Create new file record in database."""
        if not conversation_id and not project_id:
            raise ValueError("conversation_id or project_id must be provided")

        if blob_object_id:
            resolved_blob_object_id = blob_object_id
        else:
            normalized_storage_key = str(storage_key or "").strip()
            normalized_blob_url = str(blob_url or "").strip()
            if not normalized_storage_key or not normalized_blob_url:
                raise ValueError("storage_key and blob_url are required when blob_object_id is not provided")
            blob_object = self._create_blob_object(
                db=db,
                storage_key=normalized_storage_key,
                blob_url=normalized_blob_url,
            )
            resolved_blob_object_id = str(blob_object.id)

        file_record = File(
            user_id=user_id, conversation_id=conversation_id, project_id=project_id,
            blob_object_id=resolved_blob_object_id,
            original_filename=original_filename, file_type=file_type,
            file_size=file_size, content_hash=content_hash,
            processing_status=processing_status,
        )
        file_record.extracted_text = extracted_text
        db.add(file_record)
        db.flush()

        try:
            analytics_event_recorder.record_file_upload(db, user_id=user_id, file_size_bytes=file_size, file_type=file_type)
        except Exception as exc:
            log_event(
                logger,
                "WARNING",
                "admin.stats.file_upload_record_failed",
                "retry",
                user_id=user_id,
                file_type=file_type,
                file_size=file_size,
                exc_info=exc,
            )

        if commit:
            db.commit()
            db.refresh(file_record)
        return file_record

    def create_staged_file_record(
        self,
        *,
        user_id: str,
        original_filename: str,
        file_type: str,
        file_size: int,
        content_hash: str,
        extracted_text: Optional[str],
        draft_id: Optional[str],
        db: Session,
        storage_key: Optional[str] = None,
        blob_url: Optional[str] = None,
        blob_object_id: Optional[str] = None,
        commit: bool = False,
        processing_status: str = "pending",
        processing_error: Optional[str] = None,
        redaction_requested: bool = False,
        redaction_applied: bool = False,
        redacted_categories: Optional[List[str]] = None,
    ) -> StagedFile:
        if blob_object_id:
            resolved_blob_object_id = blob_object_id
        else:
            normalized_storage_key = str(storage_key or "").strip()
            normalized_blob_url = str(blob_url or "").strip()
            if not normalized_storage_key or not normalized_blob_url:
                raise ValueError("storage_key and blob_url are required when blob_object_id is not provided")
            blob_object = self._create_blob_object(
                db=db,
                storage_key=normalized_storage_key,
                blob_url=normalized_blob_url,
            )
            resolved_blob_object_id = str(blob_object.id)

        staged = StagedFile(
            user_id=user_id, draft_id=draft_id, blob_object_id=resolved_blob_object_id,
            original_filename=original_filename, file_type=file_type, file_size=file_size,
            content_hash=content_hash,
            processing_status=processing_status,
            processing_error=processing_error,
            redaction_requested=bool(redaction_requested),
            redaction_applied=bool(redaction_applied),
            redacted_categories_jsonb=list(redacted_categories or []),
        )
        staged.extracted_text = extracted_text
        db.add(staged)
        db.flush()
        if commit:
            db.commit()
            db.refresh(staged)
        return staged

    # =========================================================================
    # File Queries
    # =========================================================================

    def get_conversation_files(self, conversation_id: str, user_id: str, db: Session) -> List[File]:
        """Get all files for a conversation (excludes extracted_text)."""
        return db.query(File).options(
            load_only(
                File.id, File.blob_object_id, File.original_filename, File.file_type,
                File.file_size, File.processing_status, File.created_at,
                File.conversation_id, File.user_id, File.parent_file_id,
            ),
            selectinload(File.blob_object).load_only(
                BlobObject.storage_key, BlobObject.blob_url, BlobObject.purged_at,
            ),
        ).filter(
            and_(File.conversation_id == conversation_id, File.user_id == user_id)
        ).order_by(File.created_at.desc()).all()

    def get_child_images_by_parent_ids(
        self, parent_ids: List[str], db: Session, *, limit_per_parent: Optional[int] = None,
    ) -> Dict[str, List[File]]:
        """Return mapping of parent_file_id -> list[File]."""
        if not parent_ids:
            return {}
        rows = db.query(File).options(
            load_only(
                File.id, File.blob_object_id, File.original_filename, File.file_type,
                File.file_size, File.processing_status, File.created_at, File.parent_file_id,
            ),
            selectinload(File.blob_object).load_only(
                BlobObject.storage_key, BlobObject.blob_url, BlobObject.purged_at,
            ),
        ).filter(File.parent_file_id.in_(parent_ids)).order_by(File.created_at.asc()).all()

        grouped: Dict[str, List[File]] = {}
        for f in rows:
            if f.parent_file_id:
                grouped.setdefault(f.parent_file_id, []).append(f)
        if limit_per_parent and limit_per_parent > 0:
            for pid in grouped:
                grouped[pid] = grouped[pid][:limit_per_parent]
        return grouped

    def get_file_with_content(self, file_id: str, db: Session, *, user_id: Optional[str] = None) -> Optional[File]:
        """Load a file including its extracted_text."""
        query = db.query(File).options(
            selectinload(File.text_content),
        ).filter(File.id == file_id)
        if user_id:
            query = query.filter(File.user_id == user_id)
        return query.first()

    def get_project_files(self, project_id: str, db: Session) -> List[File]:
        """Get all top-level knowledge base files for a project."""
        return db.query(File).options(
            load_only(
                File.id, File.user_id, File.project_id, File.blob_object_id, File.original_filename,
                File.file_type, File.file_size, File.content_hash, File.created_at, File.updated_at,
                File.processing_status, File.indexed_chunk_count, File.indexed_at, File.processing_error,
            ),
            selectinload(File.blob_object).load_only(
                BlobObject.storage_key, BlobObject.blob_url, BlobObject.purged_at,
            ),
            joinedload(File.user).load_only(User.id, User.name, User.email),
        ).filter(
            and_(File.project_id == project_id, File.parent_file_id.is_(None))
        ).order_by(File.created_at.desc()).all()

    def get_project_files_page(
        self,
        project_id: str,
        db: Session,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get a paginated page of top-level knowledge base files for a project."""
        normalized_limit = max(1, min(int(limit or 50), 200))
        normalized_offset = max(0, int(offset or 0))
        scope_filter = and_(File.project_id == project_id, File.parent_file_id.is_(None))

        total_files = int(
            db.query(func.count(File.id))
            .filter(scope_filter)
            .scalar()
            or 0
        )

        files = (
            db.query(File)
            .options(
                load_only(
                    File.id,
                    File.user_id,
                    File.project_id,
                    File.blob_object_id,
                    File.original_filename,
                    File.file_type,
                    File.file_size,
                    File.content_hash,
                    File.created_at,
                    File.updated_at,
                    File.processing_status,
                    File.indexed_chunk_count,
                    File.indexed_at,
                    File.processing_error,
                ),
                selectinload(File.blob_object).load_only(
                    BlobObject.storage_key,
                    BlobObject.blob_url,
                    BlobObject.purged_at,
                ),
                joinedload(File.user).load_only(User.id, User.name, User.email),
            )
            .filter(scope_filter)
            .order_by(File.created_at.desc())
            .offset(normalized_offset)
            .limit(normalized_limit)
            .all()
        )

        next_offset = normalized_offset + len(files)
        has_more = next_offset < total_files
        return {
            "files": files,
            "limit": normalized_limit,
            "offset": normalized_offset,
            "total_files": total_files,
            "has_more": has_more,
            "next_offset": next_offset if has_more else None,
        }

    def get_conversation_file_ids(self, conversation_id: str, db: Session) -> List[str]:
        """Return every file id in a conversation, including child assets."""
        rows = (
            db.query(File.id)
            .filter(File.conversation_id == conversation_id)
            .all()
        )
        return [str(file_id) for (file_id,) in rows if file_id]

    def get_project_file_aggregate_stats(self, project_id: str, db: Session) -> Dict[str, Any]:
        """Return aggregate project knowledge stats without loading full file rows."""
        scope_filter = and_(File.project_id == project_id, File.parent_file_id.is_(None))
        totals = (
            db.query(
                func.count(File.id).label("total_files"),
                func.coalesce(func.sum(File.file_size), 0).label("total_size"),
            )
            .filter(scope_filter)
            .first()
        )
        rows = (
            db.query(
                File.file_type,
                func.count(File.id).label("count"),
            )
            .filter(scope_filter)
            .group_by(File.file_type)
            .all()
        )
        return {
            "total_files": int(getattr(totals, "total_files", 0) or 0),
            "total_size": int(getattr(totals, "total_size", 0) or 0),
            "file_types": {
                str(file_type or ""): int(count or 0)
                for file_type, count in rows
                if file_type
            },
        }

    def list_project_knowledge_summary_items(
        self,
        project_id: str,
        db: Session,
        *,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Return lightweight project knowledge rows for summary/context endpoints."""
        rows = (
            db.query(
                File.id,
                File.original_filename,
                File.file_type,
                File.file_size,
                File.created_at,
            )
            .filter(and_(File.project_id == project_id, File.parent_file_id.is_(None)))
            .order_by(File.created_at.desc())
            .limit(max(1, limit))
            .all()
        )
        return [
            {
                "file_id": str(file_id),
                "original_filename": original_filename,
                "file_type": file_type,
                "file_size": int(file_size or 0),
                "created_at": created_at,
            }
            for file_id, original_filename, file_type, file_size, created_at in rows
            if file_id
        ]

    def build_project_files_archive(self, project_id: str, db: Session) -> Dict[str, Any]:
        """Build a ZIP archive for all top-level project knowledge files."""
        files = (
            db.query(File)
            .options(
                load_only(File.id, File.blob_object_id, File.original_filename, File.created_at),
                selectinload(File.blob_object).load_only(
                    BlobObject.storage_key, BlobObject.blob_url, BlobObject.purged_at,
                ),
            )
            .filter(and_(File.project_id == project_id, File.parent_file_id.is_(None)))
            .order_by(File.created_at.asc())
            .all()
        )
        if not files:
            raise ValueError("No project knowledge files found")

        archive_file = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
        seen_names: set[str] = set()
        included_count = 0
        skipped_count = 0

        with zipfile.ZipFile(
            archive_file,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as zip_handle:
            for file_row in files:
                blob_bytes = blob_storage_service.get_bytes(file_row.filename)
                if blob_bytes is None:
                    skipped_count += 1
                    continue

                entry_name = self._ensure_unique_archive_name(
                    file_row.original_filename or file_row.filename or "file",
                    seen_names,
                )
                zip_handle.writestr(entry_name, blob_bytes)
                included_count += 1

            if skipped_count > 0:
                zip_handle.writestr(
                    "DOWNLOAD_NOTES.txt",
                    (
                        f"{skipped_count} file(s) were skipped because source bytes "
                        "were unavailable in blob storage."
                    ),
                )

        archive_file.seek(0)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        archive_name = f"project-knowledge-{project_id[:8]}-{timestamp}.zip"
        return {
            "archive_file": archive_file,
            "archive_name": archive_name,
            "total": len(files),
            "included": included_count,
            "skipped": skipped_count,
        }

    def get_project_files_stats(self, project_id: str, db: Session) -> Dict[str, Any]:
        """Get statistics about knowledge base files in a project."""
        files = self.get_project_files(project_id, db)
        aggregates = self.get_project_file_aggregate_stats(project_id, db)
        return {
            "total_files": aggregates["total_files"],
            "total_size": aggregates["total_size"],
            "file_types": aggregates["file_types"],
            "files": files,
        }

    def get_project_knowledge_overview(self, project_id: str, db: Session, *, limit: int = 12) -> Dict[str, Any]:
        """Return lightweight metadata about project knowledge files."""
        rows = (
            db.query(
                File.id,
                File.original_filename,
                File.file_type,
                File.file_size,
                File.created_at,
                func.count(File.id).over().label("total_files"),
            )
            .filter(and_(File.project_id == project_id, File.parent_file_id.is_(None)))
            .order_by(File.created_at.desc())
            .limit(max(1, limit))
            .all()
        )

        total_files = int(rows[0][5]) if rows else 0

        return {
            "total_files": total_files,
            "files": [{"id": r[0], "name": r[1], "type": r[2], "size": r[3], "created_at": r[4]} for r in rows],
        }

    async def get_project_knowledge_overview_async(
        self,
        project_id: str,
        db: AsyncSession,
        *,
        limit: int = 12,
    ) -> Dict[str, Any]:
        """Async lightweight metadata about project knowledge files."""
        stmt = (
            select(
                File.id,
                File.original_filename,
                File.file_type,
                File.file_size,
                File.created_at,
                func.count(File.id).over().label("total_files"),
            )
            .where(
                and_(File.project_id == project_id, File.parent_file_id.is_(None))
            )
            .order_by(File.created_at.desc())
            .limit(max(1, limit))
        )
        rows = (await db.execute(stmt)).all()
        total_files = int(rows[0][5]) if rows else 0
        return {
            "total_files": total_files,
            "files": [{"id": r[0], "name": r[1], "type": r[2], "size": r[3], "created_at": r[4]} for r in rows],
        }

    def get_file_by_id(
        self,
        file_id: str,
        user_id: str,
        db: Session,
        *,
        include_text: bool = False,
        include_uploader: bool = False,
    ) -> Optional[File]:
        """Get file by ID with access control."""
        query = self._file_response_query(
            db,
            include_text=include_text,
            include_uploader=include_uploader,
        )
        return (
            query
            .outerjoin(
                ProjectMember,
                and_(
                    ProjectMember.project_id == File.project_id,
                    ProjectMember.user_id == user_id,
                ),
            )
            .filter(
                File.id == file_id,
                or_(
                    File.user_id == user_id,
                    ProjectMember.id.isnot(None),
                ),
            )
            .first()
        )

    async def get_file_by_id_async(
        self,
        file_id: str,
        user_id: str,
        db: AsyncSession,
        *,
        include_text: bool = False,
        include_uploader: bool = False,
    ) -> Optional[File]:
        """Async get file by ID with access control."""
        options = [
            selectinload(File.blob_object).load_only(
                BlobObject.storage_key,
                BlobObject.blob_url,
                BlobObject.purged_at,
            ),
        ]
        if include_text:
            options.append(selectinload(File.text_content))
        if include_uploader:
            options.append(joinedload(File.user).load_only(User.id, User.name, User.email))

        stmt = (
            select(File)
            .options(*options)
            .outerjoin(
                ProjectMember,
                and_(
                    ProjectMember.project_id == File.project_id,
                    ProjectMember.user_id == user_id,
                ),
            )
            .where(
                File.id == file_id,
                or_(
                    File.user_id == user_id,
                    ProjectMember.id.is_not(None),
                ),
            )
        )
        return (await db.scalars(stmt)).first()

    def get_staged_by_id(self, staged_id: str, user_id: str, db: Session) -> Optional[StagedFile]:
        return (
            self._staged_file_response_query(db)
            .options(
                load_only(
                    StagedFile.id,
                    StagedFile.user_id,
                    StagedFile.draft_id,
                    StagedFile.blob_object_id,
                    StagedFile.original_filename,
                    StagedFile.file_type,
                    StagedFile.file_size,
                    StagedFile.content_hash,
                    StagedFile.processing_status,
                    StagedFile.processing_error,
                    StagedFile.processed_at,
                    StagedFile.redaction_requested,
                    StagedFile.redaction_applied,
                    StagedFile.redacted_categories_jsonb,
                    StagedFile.created_at,
                    StagedFile.expires_at,
                ),
            )
            .filter(and_(StagedFile.id == staged_id, StagedFile.user_id == user_id))
            .first()
        )

    async def get_staged_by_id_async(
        self,
        staged_id: str,
        user_id: str,
        db: AsyncSession,
    ) -> Optional[StagedFile]:
        stmt = (
            select(StagedFile)
            .options(
                selectinload(StagedFile.blob_object).load_only(
                    BlobObject.storage_key,
                    BlobObject.blob_url,
                    BlobObject.purged_at,
                ),
                selectinload(StagedFile.text_content),
                load_only(
                    StagedFile.id,
                    StagedFile.user_id,
                    StagedFile.draft_id,
                    StagedFile.blob_object_id,
                    StagedFile.original_filename,
                    StagedFile.file_type,
                    StagedFile.file_size,
                    StagedFile.content_hash,
                    StagedFile.processing_status,
                    StagedFile.processing_error,
                    StagedFile.processed_at,
                    StagedFile.redaction_requested,
                    StagedFile.redaction_applied,
                    StagedFile.redacted_categories_jsonb,
                    StagedFile.created_at,
                    StagedFile.expires_at,
                ),
            )
            .where(
                StagedFile.id == staged_id,
                StagedFile.user_id == user_id,
            )
        )
        return (await db.scalars(stmt)).first()

    def get_staged_by_draft_id(self, draft_id: str, user_id: str, db: Session) -> List[StagedFile]:
        return db.query(StagedFile).filter(
            and_(StagedFile.draft_id == draft_id, StagedFile.user_id == user_id)
        ).all()

    def get_conversation_files_stats(self, conversation_id: str, user_id: str, db: Session) -> Dict[str, Any]:
        """Get statistics about files in a conversation."""
        files = self.get_conversation_files(conversation_id, user_id, db)
        file_types: Dict[str, int] = {}
        for f in files:
            file_types[f.file_type] = file_types.get(f.file_type, 0) + 1
        return {"total_files": len(files), "total_size": sum(f.file_size for f in files), "file_types": file_types, "files": files}

    def get_project_file_processing_status(self, project_id: str, db: Session) -> Dict[str, Any]:
        """Get processing status summary for all files in a project."""
        statuses = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        status_expr = func.lower(func.coalesce(File.processing_status, "completed"))
        rows = (
            db.query(
                status_expr.label("status"),
                func.count(File.id).label("count"),
            )
            .filter(File.project_id == project_id, File.parent_file_id.is_(None))
            .group_by(status_expr)
            .all()
        )

        total = 0
        for status_value, count_value in rows:
            status = str(status_value or "completed").strip().lower()
            if status not in statuses:
                status = "failed"
            count = int(count_value or 0)
            statuses[status] = statuses.get(status, 0) + count
            total += count

        return {
            "total": total,
            **statuses,
            "all_completed": (
                statuses["pending"] == 0
                and statuses["processing"] == 0
                and statuses["failed"] == 0
            ),
        }

    # =========================================================================
    # File Deletion
    # =========================================================================

    def delete_file(self, file_id: str, user_id: str, db: Session) -> bool:
        """Delete file from database and blob storage."""
        file_record = self.get_file_by_id(file_id, user_id, db)
        if not file_record:
            return False

        children = db.query(File).filter(File.parent_file_id == file_record.id).all()
        files_to_delete = [*children, file_record]
        candidate_blob_ids = [
            str(getattr(row, "blob_object_id", "") or "")
            for row in files_to_delete
            if getattr(row, "blob_object_id", None)
        ]

        # Delete child images first
        for child in children:
            db.delete(child)

        db.delete(file_record)
        db.flush()
        self._cleanup_orphan_blob_objects(
            db=db,
            blob_object_ids=candidate_blob_ids,
        )
        db.commit()
        return True

    def delete_project_files(self, project_id: str, db: Session) -> int:
        """Delete all top-level knowledge base files for a project (and their children, chunks, outbox rows)."""
        top_level = db.query(File).filter(
            File.project_id == project_id,
            File.parent_file_id.is_(None),
        ).all()
        if not top_level:
            return 0

        top_ids = [f.id for f in top_level]

        # Delete chunks and outbox rows
        db.query(ProjectFileChunk).filter(ProjectFileChunk.project_id == project_id).delete(synchronize_session=False)
        db.query(ProjectFileIndexOutbox).filter(ProjectFileIndexOutbox.project_id == project_id).delete(synchronize_session=False)

        # Delete child files (images etc.) and their blobs
        children = db.query(File).filter(File.parent_file_id.in_(top_ids)).all()
        files_to_delete = [*children, *top_level]
        candidate_blob_ids = [
            str(getattr(row, "blob_object_id", "") or "")
            for row in files_to_delete
            if getattr(row, "blob_object_id", None)
        ]

        for child in children:
            db.delete(child)

        for f in top_level:
            db.delete(f)

        db.flush()
        self._cleanup_orphan_blob_objects(
            db=db,
            blob_object_ids=candidate_blob_ids,
        )
        db.commit()
        return len(top_level)

    def delete_staged_file(self, staged_id: str, user_id: str, db: Session) -> bool:
        staged = self.get_staged_by_id(staged_id, user_id, db)
        if not staged:
            return False
        staged_blob_id = str(getattr(staged, "blob_object_id", "") or "")
        db.delete(staged)
        db.flush()
        if staged_blob_id:
            self._cleanup_orphan_blob_objects(
                db=db,
                blob_object_ids=[staged_blob_id],
            )
        db.commit()
        return True

    def delete_staged_files_by_draft_id(self, draft_id: str, user_id: str, db: Session) -> int:
        if not draft_id:
            return 0

        staged_files = self.get_staged_by_draft_id(draft_id, user_id, db)
        if not staged_files:
            return 0

        staged_blob_ids: List[str] = []
        for staged in staged_files:
            blob_object_id = str(getattr(staged, "blob_object_id", "") or "")
            if blob_object_id:
                staged_blob_ids.append(blob_object_id)
            db.delete(staged)

        db.flush()
        if staged_blob_ids:
            self._cleanup_orphan_blob_objects(
                db=db,
                blob_object_ids=staged_blob_ids,
            )
        db.commit()
        return len(staged_files)

    # =========================================================================
    # File Chunk Reading
    # =========================================================================

    def _read_project_chunk_from_index(
        self,
        *,
        file_record: File,
        start: int,
        length: int,
        db: Session,
    ) -> Dict[str, Any]:
        requested_end = start + length
        max_char_end = (
            db.query(func.max(ProjectFileChunk.char_end))
            .filter(ProjectFileChunk.file_id == file_record.id)
            .scalar()
        )
        total_length = int(max_char_end or 0)

        if total_length <= 0:
            raise RuntimeError(
                "Project file is not indexed yet. Please retry once indexing completes."
            )

        bounded_start = min(start, total_length)
        bounded_end = min(requested_end, total_length)
        if bounded_end <= bounded_start:
            return {
                "file_id": file_record.id,
                "filename": file_record.filename,
                "original_filename": file_record.original_filename,
                "file_type": file_record.file_type,
                "content": "",
                "chunk_start": bounded_start,
                "chunk_end": bounded_start,
                "total_length": total_length,
                "has_more": bounded_start < total_length,
                "is_truncated": bounded_start < total_length,
                "encoding": "utf-8",
                "metadata": {"source": "project_file_chunks", "offset_unit": "characters"},
                "project_id": file_record.project_id,
                "conversation_id": file_record.conversation_id,
                "checksum": file_record.content_hash,
            }

        overlapping_chunks = (
            db.query(ProjectFileChunk)
            .filter(
                ProjectFileChunk.file_id == file_record.id,
                ProjectFileChunk.char_end > bounded_start,
                ProjectFileChunk.char_start < bounded_end,
            )
            .order_by(ProjectFileChunk.chunk_index.asc())
            .all()
        )

        if not overlapping_chunks:
            raise RuntimeError(
                "Project file is not indexed yet. Please retry once indexing completes."
            )

        parts: List[str] = []
        cursor = bounded_start
        for chunk in overlapping_chunks:
            local_start = max(cursor, int(chunk.char_start))
            local_end = min(bounded_end, int(chunk.char_end))
            if local_end <= local_start:
                continue
            source_start = local_start - int(chunk.char_start)
            source_end = local_end - int(chunk.char_start)
            part = (chunk.chunk_text or "")[source_start:source_end]
            if part:
                parts.append(part)
                cursor = local_end
            if cursor >= bounded_end:
                break

        content = "".join(parts)
        chunk_end = bounded_start + len(content)

        return {
            "file_id": file_record.id,
            "filename": file_record.filename,
            "original_filename": file_record.original_filename,
            "file_type": file_record.file_type,
            "content": content,
            "chunk_start": bounded_start,
            "chunk_end": chunk_end,
            "total_length": total_length,
            "has_more": chunk_end < total_length,
            "is_truncated": chunk_end < total_length,
            "encoding": "utf-8",
            "metadata": {"source": "project_file_chunks", "offset_unit": "characters"},
            "project_id": file_record.project_id,
            "conversation_id": file_record.conversation_id,
            "checksum": file_record.content_hash,
        }

    def read_file_chunk(
        self,
        file_id: str,
        user_id: str,
        start: int,
        length: int,
        db: Session,
        *,
        allow_full: bool = False,
    ) -> Dict[str, Any]:
        """Return a slice of file content."""
        if start < 0:
            raise ValueError("'start' must be >= 0")
        if length <= 0:
            raise ValueError("'length' must be > 0")

        max_length = settings.file_chunk_max_length
        if not allow_full and max_length and length > max_length:
            length = max_length

        file_record = self.get_file_by_id(file_id, user_id, db, include_text=True)
        if not file_record:
            raise FileNotFoundError("File not found")

        if file_record.project_id:
            return self._read_project_chunk_from_index(
                file_record=file_record,
                start=start,
                length=length,
                db=db,
            )

        extracted_text = file_record.extracted_text or ""
        if extracted_text:
            total_length = len(extracted_text)
            start = min(start, total_length)
            chunk_end = min(start + length, total_length)
            return {
                "file_id": file_record.id, "filename": file_record.filename,
                "original_filename": file_record.original_filename, "file_type": file_record.file_type,
                "content": extracted_text[start:chunk_end], "chunk_start": start, "chunk_end": chunk_end,
                "total_length": total_length, "has_more": chunk_end < total_length,
                "is_truncated": chunk_end < total_length, "encoding": "utf-8",
                "metadata": {"source": "extracted_text", "offset_unit": "characters"},
                "project_id": file_record.project_id, "conversation_id": file_record.conversation_id,
                "checksum": file_record.content_hash,
            }

        if not file_record.filename:
            raise RuntimeError("File content has been purged")

        if not blob_storage_service.blob_client:
            raise RuntimeError("Parsed content unavailable and blob client not configured")

        start = min(start, file_record.file_size)
        raw_bytes = blob_storage_service.download_range(file_record.filename, start, length)
        content = raw_bytes.decode("utf-8", errors="replace")
        bytes_end = min(start + len(raw_bytes), file_record.file_size)

        return {
            "file_id": file_record.id, "filename": file_record.filename,
            "original_filename": file_record.original_filename, "file_type": file_record.file_type,
            "content": content, "chunk_start": start, "chunk_end": bytes_end,
            "total_length": file_record.file_size, "has_more": bytes_end < file_record.file_size,
            "is_truncated": bytes_end < file_record.file_size, "encoding": "utf-8",
            "metadata": {"source": "blob_storage", "offset_unit": "bytes"},
            "project_id": file_record.project_id, "conversation_id": file_record.conversation_id,
            "checksum": file_record.content_hash,
        }

    # =========================================================================
    # Staged File Promotion
    # =========================================================================

    def promote_staged_files_to_conversation(
        self, *, staged_ids: List[str], user_id: str, conversation_id: str, db: Session,
    ) -> List[File]:
        """Convert staged files into real files attached to a conversation."""
        if not staged_ids:
            return []

        staged_list = (
            db.query(StagedFile)
            .options(selectinload(StagedFile.text_content))
            .filter(and_(StagedFile.user_id == user_id, StagedFile.id.in_(staged_ids)))
            .all()
        )
        if not staged_list:
            return []
        incomplete = [
            staged.id
            for staged in staged_list
            if str(getattr(staged, "processing_status", "") or "").strip().lower() != "completed"
        ]
        if incomplete:
            raise ValueError("Attachments are still processing")

        parent_ids = [s.id for s in staged_list if s.id]
        content_hashes = list({s.content_hash for s in staged_list if s.content_hash})

        promoted: List[File] = []
        to_delete_ids: set[str] = {s.id for s in staged_list if s.id}

        existing_in_conversation_by_hash: Dict[str, File] = {}
        if content_hashes:
            conversation_rows = (
                db.query(File)
                .filter(
                    and_(
                        File.user_id == user_id,
                        File.conversation_id == conversation_id,
                        File.parent_file_id.is_(None),
                        File.content_hash.in_(content_hashes),
                    )
                )
                .order_by(File.content_hash.asc(), File.created_at.desc())
                .all()
            )
            for row in conversation_rows:
                if row.content_hash and row.content_hash not in existing_in_conversation_by_hash:
                    existing_in_conversation_by_hash[row.content_hash] = row

        child_by_parent: Dict[str, List[StagedFile]] = {}
        if parent_ids:
            child_rows = (
                db.query(StagedFile)
                .options(selectinload(StagedFile.text_content))
                .filter(StagedFile.parent_staged_id.in_(parent_ids))
                .all()
            )
            for child in child_rows:
                if child.parent_staged_id:
                    child_by_parent.setdefault(child.parent_staged_id, []).append(child)

        for staged in staged_list:
            file_row: File
            if staged.content_hash in existing_in_conversation_by_hash:
                file_row = existing_in_conversation_by_hash[staged.content_hash]
            else:
                file_row = self.create_file_record(
                    user_id=user_id, original_filename=staged.original_filename,
                    file_type=staged.file_type, file_size=staged.file_size, content_hash=staged.content_hash,
                    blob_object_id=staged.blob_object_id, extracted_text=staged.extracted_text,
                    db=db, conversation_id=conversation_id, commit=False,
                )
            if staged.content_hash:
                existing_in_conversation_by_hash[staged.content_hash] = file_row
            promoted.append(file_row)

            # Promote child staged images
            for child in child_by_parent.get(staged.id, []):
                try:
                    child_file = self.create_file_record(
                        user_id=user_id, original_filename=child.original_filename,
                        file_type=child.file_type, file_size=child.file_size, content_hash=child.content_hash,
                        blob_object_id=child.blob_object_id, extracted_text=child.extracted_text,
                        db=db, conversation_id=conversation_id, commit=False,
                    )
                    child_file.parent_file_id = file_row.id
                    to_delete_ids.add(child.id)
                except Exception as exc:
                    log_event(
                        logger,
                        "WARNING",
                        "file.staged_child_promotion_failed",
                        "retry",
                        child_staged_id=child.id,
                        conversation_id=conversation_id,
                        exc_info=exc,
                    )

        # Delete staged records (will be committed with caller's transaction)
        if to_delete_ids:
            (
                db.query(StagedFile)
                .filter(and_(StagedFile.user_id == user_id, StagedFile.id.in_(list(to_delete_ids))))
                .delete(synchronize_session=False)
            )

        return promoted


# Singleton instance
file_service = FileService()
