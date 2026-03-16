"""Helpers for cloning message-store conversation history."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from ...database.models import Conversation, File, Message, MessagePart

def _extract_attachment_ids_from_part_payload(payload: Dict[str, Any]) -> Set[str]:
    file_ids: Set[str] = set()
    attachments = payload.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            fid = attachment.get("id")
            if isinstance(fid, str) and fid:
                file_ids.add(fid)
    attachment_ids = payload.get("attachment_ids")
    if isinstance(attachment_ids, list):
        for fid in attachment_ids:
            if isinstance(fid, str) and fid:
                file_ids.add(fid)
    return file_ids


def collect_file_ids_from_messages(messages: List[Message]) -> Set[str]:
    file_ids: Set[str] = set()
    for message in messages:
        for part in getattr(message, "parts", []) or []:
            if not isinstance(part, MessagePart):
                continue
            if str(part.part_type or "").strip().lower() != "metadata":
                continue
            payload = part.payload_jsonb if isinstance(part.payload_jsonb, dict) else {}
            file_ids.update(_extract_attachment_ids_from_part_payload(payload))
    return file_ids


def clone_files_with_mapping(
    file_ids: Set[str],
    source_conversation_id: str,
    target_conversation_id: str,
    db: Session,
) -> Dict[str, str]:
    file_id_map: Dict[str, str] = {}
    if not file_ids:
        return file_id_map

    originals = (
        db.query(File)
        .filter(
            File.conversation_id == source_conversation_id,
            File.id.in_(list(file_ids)),
        )
        .all()
    )

    duplicates: List[Tuple[File, File]] = []
    for original_file in originals:
        duplicated_file = File(
            user_id=original_file.user_id,
            conversation_id=target_conversation_id,
            blob_object_id=original_file.blob_object_id,
            original_filename=original_file.original_filename,
            file_type=original_file.file_type,
            file_size=original_file.file_size,
            content_hash=original_file.content_hash,
            processing_status=original_file.processing_status,
        )
        duplicated_file.extracted_text = original_file.extracted_text
        duplicated_file.created_at = original_file.created_at
        duplicated_file.updated_at = original_file.updated_at
        db.add(duplicated_file)
        duplicates.append((original_file, duplicated_file))

    db.flush()

    for original_file, duplicated_file in duplicates:
        file_id_map[original_file.id] = duplicated_file.id

    return file_id_map


def transform_message_metadata_for_branch(
    metadata: Optional[Dict[str, Any]],
    file_id_map: Dict[str, str],
    *,
    source_message_id: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(metadata, dict):
        metadata_copy: Dict[str, Any] = {}
    else:
        metadata_copy = deepcopy(metadata)

    attachments = metadata_copy.get("attachments")
    if isinstance(attachments, list):
        new_attachments: List[Dict[str, Any]] = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            attachment_copy = dict(attachment)
            original_id = attachment_copy.get("id")
            if isinstance(original_id, str) and original_id in file_id_map:
                attachment_copy["id"] = file_id_map[original_id]
            elif isinstance(original_id, str) and file_id_map:
                continue
            new_attachments.append(attachment_copy)
        if new_attachments:
            metadata_copy["attachments"] = new_attachments
        else:
            metadata_copy.pop("attachments", None)

    attachment_ids = metadata_copy.get("attachment_ids")
    if isinstance(attachment_ids, list) and file_id_map:
        mapped_ids = [file_id_map[fid] for fid in attachment_ids if isinstance(fid, str) and fid in file_id_map]
        if mapped_ids:
            metadata_copy["attachment_ids"] = mapped_ids
        else:
            metadata_copy.pop("attachment_ids", None)

    metadata_copy.setdefault("source_message_id", source_message_id)
    lineage = metadata_copy.get("lineage")
    if not isinstance(lineage, dict):
        lineage = {}
    else:
        lineage = dict(lineage)
    lineage.setdefault("source_message_id", source_message_id)
    metadata_copy["lineage"] = lineage
    return metadata_copy


def clone_messages_for_branch(
    messages: List[Message],
    target_conversation_id: str,
    file_id_map: Dict[str, str],
    db: Session,
) -> None:
    ordered_messages = sorted(messages, key=lambda msg: (msg.created_at, msg.id))
    for original_message in ordered_messages:
        cloned = Message(
            conversation_id=target_conversation_id,
            run_id=None,
            role=original_message.role,
            status=original_message.status,
            text=original_message.text,
            model_provider=original_message.model_provider,
            model_name=original_message.model_name,
            finish_reason=original_message.finish_reason,
            response_latency_ms=original_message.response_latency_ms,
            cost_usd=original_message.cost_usd,
            completed_at=original_message.completed_at,
        )
        cloned.created_at = original_message.created_at
        cloned.updated_at = original_message.updated_at
        db.add(cloned)
        db.flush()

        source_parts: List[MessagePart] = list(getattr(original_message, "parts", []) or [])
        if not source_parts:
            continue
        for source_part in source_parts:
            payload = source_part.payload_jsonb if isinstance(source_part.payload_jsonb, dict) else {}
            if str(source_part.part_type or "").strip().lower() == "metadata":
                payload = transform_message_metadata_for_branch(
                    payload,
                    file_id_map,
                    source_message_id=original_message.id,
                ) or {}
            db.add(
                MessagePart(
                    message_id=cloned.id,
                    ordinal=source_part.ordinal,
                    part_type=source_part.part_type,
                    phase=source_part.phase,
                    text=source_part.text,
                    payload_jsonb=deepcopy(payload),
                )
            )
        db.flush()
