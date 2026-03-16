"""Shared helpers for launching and resuming chat stream tasks."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from ...config.database import AsyncSessionLocal
from ...logging import log_event
from ...services.chat_streams import (
    StreamContext,
    get_local_stream,
    register_stream,
    schedule_cleanup,
)
from .run_snapshot_service import prepare_run_snapshot_for_resume, upsert_run_snapshot

import logging

logger = logging.getLogger(__name__)


async def _persist_initial_running_snapshot(
    *,
    conversation_id: str,
    run_id: Optional[str],
    user_message_id: str,
    assistant_message_id: Optional[str],
    status_label: str,
) -> None:
    if not isinstance(run_id, str) or not run_id.strip():
        return
    async with AsyncSessionLocal() as db:
        if isinstance(assistant_message_id, str) and assistant_message_id.strip():
            resumed = await db.run_sync(
                lambda sync_db: prepare_run_snapshot_for_resume(
                    db=sync_db,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    run_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    status_label=status_label,
                )
            )
            if not resumed:
                log_event(
                    logger,
                    "WARNING",
                    "chat.stream.resume_snapshot_missing",
                    "retry",
                    conversation_id=conversation_id,
                    run_id=run_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                )
        else:
            await db.run_sync(
                lambda sync_db: upsert_run_snapshot(
                    db=sync_db,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    run_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    status="running",
                    seq=0,
                    status_label=status_label,
                    draft_text="",
                    usage={},
                )
            )
        await db.commit()


async def launch_chat_stream(
    *,
    conversation_id: str,
    user_id: str,
    user_message_id: str,
    run_id: Optional[str] = None,
    context: Optional[StreamContext] = None,
    resume_assistant_message_id: Optional[str] = None,
    on_registered: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    """Start a chat task and register it in the Redis-backed stream registry."""
    task = await _launch_chat_stream_task(
        conversation_id=conversation_id,
        user_id=user_id,
        user_message_id=user_message_id,
        run_id=run_id,
        context=context,
        resume_assistant_message_id=resume_assistant_message_id,
        on_registered=on_registered,
    )
    del task


async def launch_chat_stream_and_wait(
    *,
    conversation_id: str,
    user_id: str,
    user_message_id: str,
    run_id: Optional[str] = None,
    context: Optional[StreamContext] = None,
    resume_assistant_message_id: Optional[str] = None,
    on_registered: Optional[Callable[[], Awaitable[None]]] = None,
) -> None:
    task = await _launch_chat_stream_task(
        conversation_id=conversation_id,
        user_id=user_id,
        user_message_id=user_message_id,
        run_id=run_id,
        context=context,
        resume_assistant_message_id=resume_assistant_message_id,
        on_registered=on_registered,
    )
    await task


async def _launch_chat_stream_task(
    *,
    conversation_id: str,
    user_id: str,
    user_message_id: str,
    run_id: Optional[str] = None,
    context: Optional[StreamContext] = None,
    resume_assistant_message_id: Optional[str] = None,
    on_registered: Optional[Callable[[], Awaitable[None]]] = None,
) -> asyncio.Task:
    """Register the stream and return the live task for optional awaiting.

    LAT-001: ``on_registered`` is called after Redis registration **and**
    initial DB snapshot persistence succeed.  The run supervisor uses this
    to defer queue acknowledgement until the run is durably started.
    """
    from ..tasks import run_chat_direct

    start_gate = asyncio.Event()
    registered = False
    initial_step = "Resuming" if isinstance(resume_assistant_message_id, str) and resume_assistant_message_id.strip() else "Starting"

    async def _run_after_registration() -> None:
        await start_gate.wait()
        await run_chat_direct(
            conversation_id,
            user_id,
            user_message_id,
            resume_assistant_message_id=resume_assistant_message_id,
        )

    task = asyncio.create_task(
        _run_after_registration()
    )
    try:
        await register_stream(
            conversation_id,
            user_id,
            user_message_id,
            run_id,
            task,
            context=context,
            current_step=initial_step,
        )
        registered = True
        await _persist_initial_running_snapshot(
            conversation_id=conversation_id,
            run_id=run_id,
            user_message_id=user_message_id,
            assistant_message_id=resume_assistant_message_id,
            status_label=initial_step,
        )
        # LAT-001: Notify caller that registration is durable before
        # releasing the task.  Queue acknowledgement must happen here,
        # NOT before registration, to prevent stranded runs on crash.
        if on_registered is not None:
            await on_registered()
        start_gate.set()
    except Exception:
        task.cancel()
        try:
            await task
        except BaseException:
            pass
        if registered:
            log_event(
                logger,
                "WARNING",
                "chat.stream.initial_runtime_snapshot_failed",
                "retry",
                conversation_id=conversation_id,
                run_id=run_id,
                user_message_id=user_message_id,
                exc_info=True,
            )
            try:
                local_stream = get_local_stream(conversation_id)
                if local_stream is not None:
                    await local_stream.set_status("failed")
                await schedule_cleanup(conversation_id)
            except Exception:
                log_event(
                    logger,
                    "WARNING",
                    "chat.stream.initial_runtime_cleanup_failed",
                    "retry",
                    conversation_id=conversation_id,
                    run_id=run_id,
                    user_message_id=user_message_id,
                    exc_info=True,
                )
        raise
    return task
