"""Service for building stream context (user, project, tools)."""

from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ...config.settings import settings
from ...database.models import Conversation, Project, User
from ...services.files import (
    blob_storage_service,
    file_search_service,
    file_service,
    search_project_chunks_hybrid,
)
from ...utils.timezone_context import build_prompt_time_context


class StreamContextBuilder:
    """Builds context for chat streaming (user, project, tools)."""

    def __init__(self) -> None:
        pass

    def load_conversation_context(
        self,
        db: Session,
        current_user_id: str,
        conversation_id: str,
        *,
        user: Optional[User] = None,
        user_timezone: Optional[str] = None,
    ) -> tuple[
        str,
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[Dict[str, Any]],
        str,
        str,
        str,
        Dict[str, Any],
    ]:
        """Load user, conversation, and project context.

        Returns:
            Tuple of (
                user_name,
                project_name,
                project_description,
                project_custom_instructions,
                project_id,
                project_files_summary,
                current_date,
                current_time,
                effective_timezone,
            )
        """
        stream_user = user or db.query(User).filter(User.id == current_user_id).first()
        user_name = stream_user.name if stream_user and stream_user.name else "User"

        stream_conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        project_name = None
        project_description = None
        project_custom_instructions = None
        project_files_summary = None
        project_id: Optional[str] = None
        base_conversation_metadata: Dict[str, Any] = {}

        if stream_conversation and stream_conversation.project_id:
            project = db.query(Project).filter(Project.id == stream_conversation.project_id).first()
            if project:
                project_name = project.name
                project_description = project.description
                project_custom_instructions = project.custom_instructions
                project_id = project.id
            try:
                overview = file_service.get_project_knowledge_overview(
                    project_id=stream_conversation.project_id,
                    db=db,
                    limit=5,
                )
                project_files_summary = self._summarize_project_files(overview)
            except Exception:
                project_files_summary = None
        if stream_conversation is not None and isinstance(stream_conversation.conversation_metadata, dict):
            base_conversation_metadata = dict(stream_conversation.conversation_metadata)

        current_date, current_time, effective_timezone = build_prompt_time_context(user_timezone)

        return (
            user_name,
            project_name,
            project_description,
            project_custom_instructions,
            project_id,
            project_files_summary,
            current_date,
            current_time,
            effective_timezone,
            base_conversation_metadata,
        )

    async def load_conversation_context_async(
        self,
        db: AsyncSession,
        current_user_id: str,
        conversation_id: str,
        *,
        user: Optional[User] = None,
        user_timezone: Optional[str] = None,
    ) -> tuple[
        str,
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[str],
        Optional[Dict[str, Any]],
        str,
        str,
        str,
        Dict[str, Any],
    ]:
        """Async variant for loading user, conversation, and project context."""
        stream_user = user or await db.scalar(select(User).where(User.id == current_user_id))
        user_name = stream_user.name if stream_user and stream_user.name else "User"

        stream_conversation = await db.scalar(select(Conversation).where(Conversation.id == conversation_id))
        project_name = None
        project_description = None
        project_custom_instructions = None
        project_files_summary = None
        project_id: Optional[str] = None
        base_conversation_metadata: Dict[str, Any] = {}

        if stream_conversation and stream_conversation.project_id:
            project = await db.scalar(select(Project).where(Project.id == stream_conversation.project_id))
            if project:
                project_name = project.name
                project_description = project.description
                project_custom_instructions = project.custom_instructions
                project_id = project.id
            try:
                overview = await file_service.get_project_knowledge_overview_async(
                    project_id=stream_conversation.project_id,
                    db=db,
                    limit=5,
                )
                project_files_summary = self._summarize_project_files(overview)
            except Exception:
                project_files_summary = None
        if stream_conversation is not None and isinstance(stream_conversation.conversation_metadata, dict):
            base_conversation_metadata = dict(stream_conversation.conversation_metadata)

        current_date, current_time, effective_timezone = build_prompt_time_context(user_timezone)

        return (
            user_name,
            project_name,
            project_description,
            project_custom_instructions,
            project_id,
            project_files_summary,
            current_date,
            current_time,
            effective_timezone,
            base_conversation_metadata,
        )

    def build_tool_context(
        self,
        db: Optional[Session],
        current_user_id: str,
        conversation_id: str,
        allowed_file_ids: Set[str],
        project_id: Optional[str] = None,
        current_user: Optional[User] = None,
        user_timezone: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build tool execution context."""
        resolved_timezone = user_timezone
        if not resolved_timezone and current_user:
            resolved_timezone = getattr(current_user, "timezone", None)

        return {
            "user_id": current_user_id,
            "conversation_id": conversation_id,
            "project_id": project_id,
            "timezone": resolved_timezone,  # User timezone for date-sensitive tools
            "db": db,
            "file_service": file_service,
            "file_search_service": file_search_service,
            "project_search_service": search_project_chunks_hybrid,
            "blob_storage_service": blob_storage_service,
            "allowed_file_ids": list(allowed_file_ids),
            "max_chunk_length": settings.file_chunk_max_length,
            "file_chunk_cache": {},
        }

    def _summarize_project_files(self, overview: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Summarize project knowledge files for prompt injection."""
        if not overview:
            return None
        files = overview.get("files")
        if not isinstance(files, list) or not files:
            return None

        max_entries = 5
        summary_files: List[Dict[str, Optional[str]]] = []
        for item in files[:max_entries]:
            if not isinstance(item, dict):
                continue
            file_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or item.get("original_filename") or "Untitled file").strip()
            summary_files.append(
                {
                    "id": file_id or None,
                    "name": name or "Untitled file",
                }
            )

        if not summary_files:
            return None

        total_files = int(overview.get("total_files", len(files)) or len(files))
        remaining = max(0, total_files - len(summary_files))

        return {
            "files": summary_files,
            "remaining": remaining,
            "total_files": total_files,
        }
