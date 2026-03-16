from __future__ import annotations

import asyncio
import logging
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File as FastAPIFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..config.database import AsyncSessionLocal, call_db_method as _call_db_method, get_async_db as get_db, run_db as _run_db
from ..database.models import File as FileModel
from ..database.models import Project, ProjectArchiveJob, User
from ..logging import log_event
from ..schemas.files import (
    ProjectKnowledgeArchiveJobResponse,
    ProjectKnowledgeBulkDeleteResponse,
    ProjectKnowledgeContextResponse,
    ProjectKnowledgeDeleteResponse,
    ProjectKnowledgeFile,
    ProjectKnowledgeFilesPageResponse,
    ProjectKnowledgeProcessingStatus,
    ProjectKnowledgeSummaryItem,
    ProjectKnowledgeSummaryResponse,
)
from ..services.files import (
    blob_storage_service,
    dispatch_project_archive_outbox_worker,
    enqueue_project_archive_outbox_event,
    file_processing_service,
    file_service,
)
from ..utils.jsonlib import json_dumps

logger = logging.getLogger(__name__)


def register_knowledge_base_routes(
    router: APIRouter,
    *,
    get_project_for_member: Callable[[str, User, Session], Project],
    serialize_project_knowledge_file: Callable[[FileModel], ProjectKnowledgeFile],
) -> None:
    async def _get_project_for_member_async(project_id: str, user: User, db: object) -> Project:
        return await _run_db(db, lambda sync_db: get_project_for_member(project_id, user, sync_db))

    def _build_processing_status_payload(project_id: str, db: Session) -> ProjectKnowledgeProcessingStatus:
        status_info = file_service.get_project_file_processing_status(project_id, db)
        return ProjectKnowledgeProcessingStatus(
            project_id=project_id,
            total=status_info["total"],
            pending=status_info["pending"],
            processing=status_info["processing"],
            completed=status_info["completed"],
            failed=status_info["failed"],
            all_completed=status_info["all_completed"],
        )

    def _build_summary_payload(project_id: str, db: Session) -> ProjectKnowledgeSummaryResponse:
        aggregate_stats = file_service.get_project_file_aggregate_stats(project_id, db)
        processing_status = file_service.get_project_file_processing_status(project_id, db)
        return ProjectKnowledgeSummaryResponse(
            project_id=project_id,
            total_files=aggregate_stats["total_files"],
            total_size=aggregate_stats["total_size"],
            file_types=aggregate_stats["file_types"],
            pending=processing_status["pending"],
            processing=processing_status["processing"],
            completed=processing_status["completed"],
            failed=processing_status["failed"],
            all_completed=processing_status["all_completed"],
        )

    def _serialize_archive_job(job: ProjectArchiveJob) -> ProjectKnowledgeArchiveJobResponse:
        download_url = None
        if str(getattr(job, "status", "") or "").strip().lower() == "completed" and getattr(job, "storage_key", None):
            try:
                download_url = blob_storage_service.build_sas_url(
                    filename=str(job.storage_key),
                    original_filename=getattr(job, "archive_filename", None),
                )
            except Exception:
                download_url = str(getattr(job, "blob_url", "") or "") or None

        return ProjectKnowledgeArchiveJobResponse(
            job_id=str(job.id),
            project_id=str(job.project_id),
            status=str(job.status),
            total_files=int(getattr(job, "total_files", 0) or 0),
            included_files=int(getattr(job, "included_files", 0) or 0),
            skipped_files=int(getattr(job, "skipped_files", 0) or 0),
            archive_filename=getattr(job, "archive_filename", None),
            download_url=download_url,
            error=getattr(job, "error", None),
            created_at=job.created_at,
            completed_at=getattr(job, "completed_at", None),
            expires_at=getattr(job, "expires_at", None),
        )

    @router.post(
        "/{project_id:uuid}/knowledge-base/upload",
        response_model=ProjectKnowledgeFile,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_project_knowledge_file(
        project_id: UUID,
        file: UploadFile = FastAPIFile(...),
        redact: bool = Query(False),
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Upload a file into the project's shared knowledge base."""
        pid = str(project_id)
        project = await _get_project_for_member_async(pid, user, db)
        current_role = getattr(project, "current_user_role", None)

        if bool(getattr(project, "is_public", False)) and current_role != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the project owner can add knowledge base files to public projects",
            )

        try:
            file_record = await file_processing_service.upload_file_for_background_processing(
                file=file,
                user_id=user.id,
                project_id=pid,
                db=db,
                redact=redact,
            )
        except HTTPException:
            raise
        except Exception as exc:
            log_event(
                logger,
                "ERROR",
                "projects.knowledge_upload.failed",
                "error",
                user_id=str(user.id),
                project_id=pid,
                filename=file.filename,
                content_type=file.content_type,
                error_type=type(exc).__name__,
                exc_info=exc,
            )
            raise HTTPException(status_code=400, detail="Failed to upload knowledge file") from exc

        return serialize_project_knowledge_file(file_record)

    @router.get(
        "/{project_id:uuid}/knowledge-base/summary",
        response_model=ProjectKnowledgeSummaryResponse,
    )
    async def get_project_knowledge_summary(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Return aggregate project knowledge stats."""
        pid = str(project_id)
        await _get_project_for_member_async(pid, user, db)
        return await _run_db(db, lambda sync_db: _build_summary_payload(pid, sync_db))

    @router.get(
        "/{project_id:uuid}/knowledge-base/files",
        response_model=ProjectKnowledgeFilesPageResponse,
    )
    async def list_project_knowledge_files(
        project_id: UUID,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """List a paginated page of knowledge base files for a project."""
        pid = str(project_id)
        await _get_project_for_member_async(pid, user, db)
        page = await _run_db(
            db,
            lambda sync_db: file_service.get_project_files_page(pid, sync_db, limit=limit, offset=offset),
        )
        return ProjectKnowledgeFilesPageResponse(
            project_id=pid,
            files=[serialize_project_knowledge_file(file) for file in page["files"]],
            limit=page["limit"],
            offset=page["offset"],
            has_more=bool(page["has_more"]),
            next_offset=page["next_offset"],
        )

    @router.get(
        "/{project_id:uuid}/knowledge-base/processing-status",
        response_model=ProjectKnowledgeProcessingStatus,
    )
    async def get_project_knowledge_processing_status(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Get the processing status of all files in a project's knowledge base."""
        pid = str(project_id)
        await _get_project_for_member_async(pid, user, db)
        return await _run_db(db, lambda sync_db: _build_processing_status_payload(pid, sync_db))

    @router.get(
        "/{project_id:uuid}/knowledge-base/processing-status/stream",
        response_class=StreamingResponse,
        responses={
            200: {
                "content": {
                    "text/event-stream": {},
                },
                "description": "Server-sent events that emit processing status updates until all files settle.",
            }
        },
    )
    async def stream_project_knowledge_processing_status(
        project_id: UUID,
        request: Request,
        user: User = Depends(get_current_user),
    ):
        """Stream project knowledge processing status updates over SSE."""
        pid = str(project_id)
        async with AsyncSessionLocal() as authz_db:
            await _get_project_for_member_async(pid, user, authz_db)

        poll_seconds = 2.0

        async def _is_disconnected() -> bool:
            try:
                return await request.is_disconnected()
            except Exception:
                return False

        async def _stream():
            last_signature = ""
            yield ": stream-open\n\n"

            while True:
                if await _is_disconnected():
                    return

                async with AsyncSessionLocal() as status_db:
                    status_payload = await _run_db(
                        status_db,
                        lambda sync_db: _build_processing_status_payload(pid, sync_db),
                    )

                status_data = status_payload.model_dump(mode="json")
                status_signature = "|".join(
                    str(status_data.get(key, ""))
                    for key in ("total", "pending", "processing", "completed", "failed", "all_completed")
                )

                if status_signature != last_signature:
                    yield f"data: {json_dumps({'type': 'processing_status', 'data': status_data})}\n\n"
                    last_signature = status_signature

                pending = int(status_data.get("pending") or 0)
                processing = int(status_data.get("processing") or 0)
                if pending <= 0 and processing <= 0:
                    yield f"data: {json_dumps({'type': 'done', 'data': {'status': 'settled'}})}\n\n"
                    return

                await asyncio.sleep(poll_seconds)

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.delete(
        "/{project_id:uuid}/knowledge-base/files",
        response_model=ProjectKnowledgeBulkDeleteResponse,
        status_code=status.HTTP_200_OK,
    )
    async def delete_all_project_knowledge_files(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Delete all knowledge base files. Only a project owner may do this."""
        pid = str(project_id)
        project = await _get_project_for_member_async(pid, user, db)
        if getattr(project, "current_user_role", None) != "owner":
            raise HTTPException(
                status_code=403,
                detail="Only a project owner can delete all knowledge base files",
            )

        deleted_count = await _run_db(db, lambda sync_db: file_service.delete_project_files(pid, sync_db))
        return ProjectKnowledgeBulkDeleteResponse(
            message=f"{deleted_count} file(s) deleted",
            deleted=deleted_count,
        )

    @router.post(
        "/{project_id:uuid}/knowledge-base/archive-jobs",
        response_model=ProjectKnowledgeArchiveJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_project_knowledge_archive_job(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Create an async archive job for project knowledge files."""
        pid = str(project_id)
        await _get_project_for_member_async(pid, user, db)

        archive_job = ProjectArchiveJob(
            project_id=pid,
            requested_by=user.id,
            status="pending",
        )
        db.add(archive_job)
        await _call_db_method(db, "flush")
        await _run_db(
            db,
            lambda sync_db: enqueue_project_archive_outbox_event(
                db=sync_db,
                archive_job_id=str(archive_job.id),
                project_id=pid,
                payload={"requested_by": user.id},
            ),
        )
        await _call_db_method(db, "commit")
        await _call_db_method(db, "refresh", archive_job)
        await asyncio.to_thread(dispatch_project_archive_outbox_worker)
        return _serialize_archive_job(archive_job)

    @router.get(
        "/{project_id:uuid}/knowledge-base/archive-jobs/{job_id}",
        response_model=ProjectKnowledgeArchiveJobResponse,
    )
    async def get_project_knowledge_archive_job(
        project_id: UUID,
        job_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Get archive job status for a project knowledge export."""
        pid = str(project_id)
        await _get_project_for_member_async(pid, user, db)
        archive_job = await _run_db(
            db,
            lambda sync_db: (
                sync_db.query(ProjectArchiveJob)
                .filter(ProjectArchiveJob.id == job_id, ProjectArchiveJob.project_id == pid)
                .first()
            ),
        )
        if not archive_job:
            raise HTTPException(status_code=404, detail="Archive job not found")
        return _serialize_archive_job(archive_job)

    @router.delete(
        "/{project_id:uuid}/knowledge-base/files/{file_id}",
        response_model=ProjectKnowledgeDeleteResponse,
        status_code=status.HTTP_200_OK,
    )
    async def delete_project_knowledge_file(
        project_id: UUID,
        file_id: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Delete a knowledge base file. Only the uploader or project owner may delete."""
        pid = str(project_id)
        project = await _get_project_for_member_async(pid, user, db)

        file_record = await _run_db(
            db,
            lambda sync_db: file_service.get_file_by_id(file_id, user.id, sync_db),
        )
        if not file_record or file_record.project_id != pid:
            raise HTTPException(status_code=404, detail="File not found")

        is_uploader = file_record.user_id == user.id
        if not is_uploader and getattr(project, "current_user_role", None) != "owner":
            raise HTTPException(
                status_code=403,
                detail="Only the uploader or a project owner can delete this file",
            )

        success = await _run_db(
            db,
            lambda sync_db: file_service.delete_file(file_id, user.id, sync_db),
        )
        if not success:
            raise HTTPException(status_code=404, detail="File not found")

        return ProjectKnowledgeDeleteResponse(message="File deleted successfully")

    @router.get(
        "/{project_id:uuid}/knowledge-base/context",
        response_model=ProjectKnowledgeContextResponse,
    )
    async def get_project_knowledge_context(
        project_id: UUID,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        """Return lightweight metadata about knowledge base files for prompt seeding."""
        pid = str(project_id)
        await _get_project_for_member_async(pid, user, db)

        aggregate_stats = await _run_db(
            db,
            lambda sync_db: file_service.get_project_file_aggregate_stats(pid, sync_db),
        )
        summary_rows = await _run_db(
            db,
            lambda sync_db: file_service.list_project_knowledge_summary_items(pid, sync_db),
        )
        summary_items = [
            ProjectKnowledgeSummaryItem(**item)
            for item in summary_rows
        ]

        return ProjectKnowledgeContextResponse(
            project_id=pid,
            total_files=aggregate_stats["total_files"],
            total_size=aggregate_stats["total_size"],
            files=summary_items,
        )
