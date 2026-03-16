"""Resolve chat stream runtime context from prefetch payloads and database."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config.database import AsyncSessionLocal
from ...database.models import User, UserPreference
from ..skills.store import (
    build_skills_prompt_section_from_db_async,
    render_skills_prompt_section,
)
from ...utils.timezone_context import build_prompt_time_context
from .stream_context_builder import StreamContextBuilder


@dataclass
class StreamRuntimeContext:
    current_user: Any
    provider_name: str
    effective_model: str
    reasoning_effort: str
    user_name: str
    project_name: Optional[str]
    project_description: Optional[str]
    project_custom_instructions: Optional[str]
    project_id: Optional[str]
    project_files_summary: Optional[Dict[str, Any]]
    current_date: str
    current_time: str
    effective_timezone: str
    user_custom_instructions: Optional[str]
    base_conversation_metadata: Dict[str, Any]
    skills_prompt_section: str


class StreamRuntimeContextLoader:
    """Loads stream context using prefetch hints and short-lived DB sessions."""

    async def load(
        self,
        *,
        prefetched_context: Dict[str, Any],
        current_user_id: str,
        conversation_id: str,
        context_builder: StreamContextBuilder,
        resolve_provider_and_model: Callable[
            [AsyncSession, Optional[User]],
            Awaitable[tuple[str, str, str]],
        ],
        coerce_metadata_dict: Callable[[Any], Dict[str, Any]],
    ) -> StreamRuntimeContext:
        current_user = None
        prefetched_user = prefetched_context.get("user")
        prefetched_user_timezone: Optional[str] = None
        if isinstance(prefetched_user, dict):
            raw_prefetched_timezone = prefetched_user.get("timezone")
            if isinstance(raw_prefetched_timezone, str) and raw_prefetched_timezone.strip():
                prefetched_user_timezone = raw_prefetched_timezone.strip()
            current_user = SimpleNamespace(
                id=str(prefetched_user.get("id") or current_user_id),
                name=prefetched_user.get("name"),
                user_tier=prefetched_user.get("user_tier"),
                model_override=prefetched_user.get("model_override"),
                timezone=prefetched_user_timezone,
            )

        prefetched_conv = prefetched_context.get("conversation_context")
        current_date: Optional[str] = None
        current_time: Optional[str] = None
        effective_timezone: Optional[str] = prefetched_user_timezone
        base_conversation_metadata: Dict[str, Any] = {}
        if isinstance(prefetched_conv, dict):
            user_name = prefetched_conv.get("user_name") or (getattr(current_user, "name", None) or "User")
            project_name = prefetched_conv.get("project_name")
            project_description = prefetched_conv.get("project_description")
            project_custom_instructions = prefetched_conv.get("project_custom_instructions")
            project_id = prefetched_conv.get("project_id")
            project_files_summary = prefetched_conv.get("project_files_summary")
            raw_base_metadata = prefetched_conv.get("base_conversation_metadata")
            if isinstance(raw_base_metadata, dict):
                base_conversation_metadata = coerce_metadata_dict(raw_base_metadata)
            raw_current_date = prefetched_conv.get("current_date")
            if isinstance(raw_current_date, str) and raw_current_date.strip():
                current_date = raw_current_date.strip()
            raw_current_time = prefetched_conv.get("current_time")
            if isinstance(raw_current_time, str) and raw_current_time.strip():
                current_time = raw_current_time.strip()
            raw_effective_timezone = prefetched_conv.get("user_timezone")
            if isinstance(raw_effective_timezone, str) and raw_effective_timezone.strip():
                effective_timezone = raw_effective_timezone.strip()
        else:
            user_name = getattr(current_user, "name", None) or "User"
            project_name = None
            project_description = None
            project_custom_instructions = None
            project_id = None
            project_files_summary = None

        prefetched_user_custom_instructions = prefetched_context.get("user_custom_instructions")
        prefetched_skills_prompt_section = prefetched_context.get("skills_prompt_section")
        skip_user_preferences_lookup = bool(prefetched_context.get("skip_user_preferences_lookup"))
        user_custom_instructions: Optional[str] = (
            prefetched_user_custom_instructions
            if isinstance(prefetched_user_custom_instructions, str)
            else None
        )
        skills_prompt_section: Optional[str] = (
            prefetched_skills_prompt_section.strip()
            if isinstance(prefetched_skills_prompt_section, str) and prefetched_skills_prompt_section.strip()
            else None
        )

        async with AsyncSessionLocal() as read_db:
            if current_user is None:
                current_user = await read_db.scalar(select(User).where(User.id == current_user_id))

            (
                provider_name,
                effective_model,
                reasoning_effort,
            ) = await resolve_provider_and_model(read_db, current_user)

            if not isinstance(prefetched_conv, dict):
                (
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
                ) = await context_builder.load_conversation_context_async(
                    read_db,
                    current_user_id,
                    conversation_id,
                    user=current_user,
                    user_timezone=effective_timezone,
                )

            if skills_prompt_section is None:
                try:
                    skills_prompt_section = await build_skills_prompt_section_from_db_async(
                        read_db,
                        user_id=current_user_id,
                    )
                except Exception:
                    skills_prompt_section = render_skills_prompt_section(set(), {})

            pref_row: Optional[UserPreference] = None
            should_load_user_pref = (
                (user_custom_instructions is None and not skip_user_preferences_lookup)
                or effective_timezone is None
            )
            if should_load_user_pref:
                try:
                    pref_row = await read_db.scalar(
                        select(UserPreference).where(UserPreference.user_id == current_user_id)
                    )
                    if user_custom_instructions is None and not skip_user_preferences_lookup:
                        maybe_custom = getattr(pref_row, "custom_instructions", None) if pref_row else None
                        user_custom_instructions = maybe_custom if isinstance(maybe_custom, str) else None
                    if effective_timezone is None and pref_row is not None:
                        maybe_timezone = getattr(pref_row, "timezone", None)
                        if isinstance(maybe_timezone, str) and maybe_timezone.strip():
                            effective_timezone = maybe_timezone.strip()
                except Exception:
                    if user_custom_instructions is None:
                        user_custom_instructions = None

        if not current_date:
            current_date, current_time, effective_timezone = build_prompt_time_context(effective_timezone)
        elif not effective_timezone:
            _, current_time, effective_timezone = build_prompt_time_context(None)
        if not current_time:
            _, current_time, _ = build_prompt_time_context(effective_timezone)

        return StreamRuntimeContext(
            current_user=current_user,
            provider_name=provider_name,
            effective_model=effective_model,
            reasoning_effort=reasoning_effort,
            user_name=user_name,
            project_name=project_name,
            project_description=project_description,
            project_custom_instructions=project_custom_instructions,
            project_id=project_id,
            project_files_summary=project_files_summary,
            current_date=current_date,
            current_time=current_time,
            effective_timezone=effective_timezone or "UTC",
            user_custom_instructions=user_custom_instructions,
            base_conversation_metadata=base_conversation_metadata,
            skills_prompt_section=skills_prompt_section or render_skills_prompt_section(set(), {}),
        )


__all__ = ["StreamRuntimeContext", "StreamRuntimeContextLoader"]
