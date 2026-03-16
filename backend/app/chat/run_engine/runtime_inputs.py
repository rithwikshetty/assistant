"""Build provider runtime inputs for a chat run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import select

from ...config.database import AsyncSessionLocal
from ...database.models import ChatRunSnapshot, Message, MessagePart
from ...services.chat_streams import StreamContext
from ...utils.coerce import coerce_non_negative_int
from ...services.files import file_service
from ..services.message_formatter import (
    append_attachment_context,
    sanitize_message_content_for_model_input,
)
from ..services.message_preparation_service import extract_allowed_file_ids
from ..services.event_history_builder import build_conversation_history_from_messages
from ..services.run_activity_service import list_run_activity_items
from ..tool_payload_sanitizer import sanitize_tool_payload_for_model


@dataclass
class PreparedRunInputs:
    """Normalized inputs for `ChatStreamingManager.stream_response`."""

    raw_messages: List[Dict[str, Any]]
    user_prompt: str
    allowed_file_ids: Set[str]
    attachments_meta: List[Dict[str, Any]]
    is_admin: bool
    seed_response_text: Optional[str] = None
    seed_tool_markers: Optional[List[Dict[str, Any]]] = None
    seed_reasoning_summaries: Optional[List[Dict[str, Any]]] = None
    seed_compaction_markers: Optional[List[Dict[str, Any]]] = None


class RunPreparationError(Exception):
    """Raised when we cannot build a valid run input window."""

    def __init__(self, *, message: str, code: str, dispatch_reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.dispatch_reason = dispatch_reason


class RunInputPreparer:
    """Load DB/context state and build prompt/history inputs."""

    async def prepare(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        stream_context: Optional[StreamContext],
        resume_assistant_message_id: Optional[str],
    ) -> PreparedRunInputs:
        allowed_file_ids: Set[str] = set()
        seed_response_text: Optional[str] = None
        seed_tool_markers: Optional[List[Dict[str, Any]]] = None
        seed_reasoning_summaries: Optional[List[Dict[str, Any]]] = None
        seed_compaction_markers: Optional[List[Dict[str, Any]]] = None

        if resume_assistant_message_id:
            (
                raw_messages,
                user_prompt,
                attachments_meta,
                seed_response_text,
                seed_tool_markers,
                seed_reasoning_summaries,
                seed_compaction_markers,
            ) = await self._prepare_resume_inputs(
                conversation_id=conversation_id,
                resume_assistant_message_id=resume_assistant_message_id,
                allowed_file_ids=allowed_file_ids,
            )
        elif stream_context and stream_context.is_new_conversation:
            raw_messages = []
            attachments_meta = stream_context.attachments_meta
            user_prompt = sanitize_message_content_for_model_input(stream_context.user_content, conversation_id)
        else:
            raw_messages, user_prompt, attachments_meta = await self._prepare_standard_inputs(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                stream_context=stream_context,
                allowed_file_ids=allowed_file_ids,
            )

        if attachments_meta:
            current_file_ids = extract_allowed_file_ids(attachments_meta)
            allowed_file_ids.update(current_file_ids)
            await self._augment_allowed_child_file_ids(
                attachments_meta=attachments_meta,
                allowed_file_ids=allowed_file_ids,
            )

        user_prompt = append_attachment_context(user_prompt, attachments_meta, allowed_file_ids)
        is_admin = stream_context.is_admin if stream_context else False

        return PreparedRunInputs(
            raw_messages=raw_messages,
            user_prompt=user_prompt,
            allowed_file_ids=allowed_file_ids,
            attachments_meta=attachments_meta,
            is_admin=is_admin,
            seed_response_text=seed_response_text,
            seed_tool_markers=seed_tool_markers,
            seed_reasoning_summaries=seed_reasoning_summaries,
            seed_compaction_markers=seed_compaction_markers,
        )

    _coerce_non_negative_int = staticmethod(coerce_non_negative_int)

    @staticmethod
    def _coerce_payload(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _seed_from_activity_rows(
        activity_rows: List[Dict[str, Any]],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        tool_markers: List[Dict[str, Any]] = []
        reasoning_summaries: List[Dict[str, Any]] = []
        compaction_markers: List[Dict[str, Any]] = []

        for row in activity_rows:
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            sequence = int(row.get("sequence") or 0)
            kind = str(row.get("kind") or "").strip().lower()

            if kind == "tool":
                tool_call_id = payload.get("tool_call_id")
                position = RunInputPreparer._coerce_non_negative_int(payload.get("position") or payload.get("pos")) or 0
                marker: Dict[str, Any] = {
                    "name": payload.get("tool_name")
                    if isinstance(payload.get("tool_name"), str)
                    else str(row.get("title") or "tool"),
                    "call_id": tool_call_id if isinstance(tool_call_id, str) and tool_call_id.strip() else f"tool_call_{sequence}",
                    "pos": position,
                    "seq": sequence,
                }
                arguments = payload.get("arguments")
                if isinstance(arguments, dict):
                    marker["arguments"] = arguments
                query = payload.get("query")
                if isinstance(query, str) and query.strip():
                    marker["query"] = query.strip()
                result = payload.get("result")
                if isinstance(result, dict):
                    marker["result"] = sanitize_tool_payload_for_model(str(marker.get("name") or ""), result)
                error = payload.get("error")
                if isinstance(error, dict):
                    marker["error"] = sanitize_tool_payload_for_model(str(marker.get("name") or ""), error)
                tool_markers.append(marker)
                continue

            if kind == "reasoning":
                marker_id = payload.get("id")
                raw_text = payload.get("raw_text")
                position = RunInputPreparer._coerce_non_negative_int(payload.get("position")) or 0
                reasoning_summaries.append(
                    {
                        "title": payload.get("title")
                        if isinstance(payload.get("title"), str)
                        else (row.get("title") or "Thinking"),
                        "raw_text": raw_text if isinstance(raw_text, str) else "",
                        "position": position,
                        "sequence": sequence,
                        "id": marker_id if isinstance(marker_id, str) and marker_id else f"seed_reasoning_{sequence}",
                    }
                )
                continue

            if kind == "compaction":
                label = payload.get("label")
                position = RunInputPreparer._coerce_non_negative_int(payload.get("position") or payload.get("pos")) or 0
                marker: Dict[str, Any] = {
                    "pos": position,
                    "seq": sequence,
                    "label": label if isinstance(label, str) and label.strip() else "Automatically compacting context",
                }
                item_id = payload.get("item_id")
                if isinstance(item_id, str) and item_id.strip():
                    marker["item_id"] = item_id.strip()
                source = payload.get("source")
                if isinstance(source, str) and source.strip():
                    marker["source"] = source.strip()
                compaction_markers.append(marker)

        return tool_markers, reasoning_summaries, compaction_markers

    async def _prepare_resume_inputs(
        self,
        *,
        conversation_id: str,
        resume_assistant_message_id: str,
        allowed_file_ids: Set[str],
    ) -> tuple[
        List[Dict[str, Any]],
        str,
        List[Dict[str, Any]],
        Optional[str],
        Optional[List[Dict[str, Any]]],
        Optional[List[Dict[str, Any]]],
        Optional[List[Dict[str, Any]]],
    ]:
        async with AsyncSessionLocal() as read_db:
            runtime_snapshot = await read_db.scalar(
                select(ChatRunSnapshot).where(
                    ChatRunSnapshot.conversation_id == conversation_id,
                    ChatRunSnapshot.assistant_message_id == resume_assistant_message_id,
                )
            )

            if runtime_snapshot is not None and runtime_snapshot.run_id:
                seed_response_text = runtime_snapshot.draft_text or ""
                activity_rows = await read_db.run_sync(
                    lambda sync_db: list_run_activity_items(
                        db=sync_db,
                        run_id=str(runtime_snapshot.run_id),
                    )
                )
                (
                    seed_tool_markers,
                    seed_reasoning_summaries,
                    seed_compaction_markers,
                ) = self._seed_from_activity_rows(activity_rows)
            else:
                raise RunPreparationError(
                    message="Runtime snapshot to resume not found",
                    code="NOT_FOUND",
                    dispatch_reason="resume_missing_runtime_snapshot",
                )

            raw_messages = await read_db.run_sync(
                lambda sync_db: build_conversation_history_from_messages(
                    sync_db,
                    conversation_id=conversation_id,
                    allowed_file_ids=allowed_file_ids,
                    anchor_user_message_id=None,
                )
            )

            # Strip the paused assistant message from history — its content
            # is reconstructed as resume_continuation by the provider.
            if raw_messages and raw_messages[-1].get("role") == "assistant":
                raw_messages.pop()

        return (
            raw_messages,
            "",
            [],
            seed_response_text,
            seed_tool_markers,
            seed_reasoning_summaries,
            seed_compaction_markers,
        )

    async def _prepare_standard_inputs(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        stream_context: Optional[StreamContext],
        allowed_file_ids: Set[str],
    ) -> tuple[List[Dict[str, Any]], str, List[Dict[str, Any]]]:
        async with AsyncSessionLocal() as read_db:
            raw_messages = await read_db.run_sync(
                lambda sync_db: build_conversation_history_from_messages(
                    sync_db,
                    conversation_id=conversation_id,
                    allowed_file_ids=allowed_file_ids,
                    anchor_user_message_id=user_message_id,
                )
            )

            if stream_context:
                attachments_meta = stream_context.attachments_meta
                user_prompt = sanitize_message_content_for_model_input(stream_context.user_content, conversation_id)
            else:
                user_message = await read_db.scalar(
                    select(Message).where(
                        Message.id == user_message_id,
                        Message.conversation_id == conversation_id,
                        Message.role == "user",
                    )
                )
                if user_message is None:
                    raise RunPreparationError(
                        message="User message not found",
                        code="NOT_FOUND",
                        dispatch_reason="missing_user_message",
                    )

                user_parts = (
                    await read_db.scalars(
                        select(MessagePart)
                        .where(MessagePart.message_id == user_message.id)
                        .order_by(MessagePart.ordinal.asc(), MessagePart.id.asc())
                    )
                ).all()
                attachments_meta: List[Dict[str, Any]] = []
                for part in user_parts:
                    if str(getattr(part, "part_type", "") or "").strip().lower() != "metadata":
                        continue
                    payload = self._coerce_payload(part.payload_jsonb)
                    attachments = payload.get("attachments")
                    if isinstance(attachments, list):
                        attachments_meta = [item for item in attachments if isinstance(item, dict)]
                        break
                raw_text = user_message.text if isinstance(user_message.text, str) else ""
                user_prompt = sanitize_message_content_for_model_input(raw_text, conversation_id)

        return raw_messages, user_prompt, attachments_meta

    async def _augment_allowed_child_file_ids(
        self,
        *,
        attachments_meta: List[Dict[str, Any]],
        allowed_file_ids: Set[str],
    ) -> None:
        try:
            parent_ids = [att.get("id") for att in attachments_meta if isinstance(att.get("id"), str)]
            if not parent_ids:
                return
            async with AsyncSessionLocal() as read_db:
                child_map = await read_db.run_sync(
                    lambda sync_db: file_service.get_child_images_by_parent_ids(
                        parent_ids=parent_ids,
                        db=sync_db,
                    )
                )
            for child_list in child_map.values():
                for child in child_list:
                    if isinstance(getattr(child, "id", None), str):
                        allowed_file_ids.add(child.id)
        except Exception:
            # Best-effort file graph expansion; never fail a run here.
            return
