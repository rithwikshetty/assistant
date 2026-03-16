"""Service for user-message preparation and attachment metadata."""

import logging
from typing import Optional, Dict, Any, List, Set, Tuple
from sqlalchemy.orm import Session
from ...database.models import File
from ...logging import log_event

logger = logging.getLogger(__name__)


def validate_and_clean_attachment_metadata(
    attachments_meta: List[Dict[str, Any]],
    user_id: str,
    conversation_id: str,
    db: Session,
) -> List[Dict[str, Any]]:
    """Validate attachment metadata and remove orphaned/invalid references.

    This is a defensive check to prevent sending invalid file references to the chat model,
    which can cause "Unable to download the file" errors.

    Args:
        attachments_meta: List of attachment metadata dictionaries
        user_id: User ID for ownership validation
        conversation_id: Conversation ID for scope validation
        db: Database session

    Returns:
        Cleaned list with only valid attachments
    """
    if not attachments_meta:
        return []

    # Extract file IDs from metadata
    file_ids = [att.get("id") for att in attachments_meta if isinstance(att.get("id"), str)]
    if not file_ids:
        return []

    # Query database to verify files exist
    existing_files = (
        db.query(File.id, File.conversation_id, File.user_id)
        .filter(File.id.in_(file_ids))
        .all()
    )

    valid_file_ids = {
        f.id for f in existing_files
        if f.user_id == user_id and f.conversation_id == conversation_id
    }

    # Filter out invalid attachments and log warnings
    cleaned_attachments = []
    for att in attachments_meta:
        file_id = att.get("id")
        if file_id in valid_file_ids:
            cleaned_attachments.append(att)
        else:
            log_event(
                logger,
                "WARNING",
                "chat.attachment.reference_filtered",
                "retry",
                file_id=file_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )

    if len(cleaned_attachments) < len(attachments_meta):
        log_event(
            logger,
            "INFO",
            "chat.attachment.orphans_removed",
            "timing",
            removed_count=len(attachments_meta) - len(cleaned_attachments),
            conversation_id=conversation_id,
        )

    return cleaned_attachments


def build_attachment_metadata_from_ids(
    attachment_ids: List[str],
    user_id: str,
    conversation_id: str,
    db: Session,
) -> List[Dict[str, Any]]:
    """Build attachment metadata list from file IDs.

    Args:
        attachment_ids: List of file IDs
        user_id: User ID (for ownership validation)
        conversation_id: Conversation ID (for scope validation)
        db: Database session

    Returns:
        List of attachment metadata dictionaries

    Raises:
        ValueError: If files are unavailable or don't belong to user/conversation
    """
    if not attachment_ids:
        return []

    files = (
        db.query(File)
        .filter(
            File.id.in_(attachment_ids),
            File.user_id == user_id,
        )
        .all()
    )

    files_by_id = {f.id: f for f in files}
    if len(files_by_id) != len(attachment_ids):
        raise ValueError("One or more attachments are unavailable or do not belong to the user.")

    attachments_meta: List[Dict[str, Any]] = []
    for fid in attachment_ids:
        file_record = files_by_id.get(fid)
        if not file_record or file_record.conversation_id != conversation_id:
            raise ValueError("Attachment does not belong to this conversation.")

        attachments_meta.append(
            {
                "id": file_record.id,
                "filename": file_record.filename,
                "original_filename": file_record.original_filename,
                "file_type": file_record.file_type,
                "file_size": int(file_record.file_size or 0),
                "uploaded_at": file_record.created_at.isoformat() + 'Z' if file_record.created_at else None,
                "checksum": file_record.content_hash,
                "blob_url": file_record.blob_url,
            }
        )

    return attachments_meta


def extract_allowed_file_ids(attachments_meta: List[Dict[str, Any]]) -> Set[str]:
    """Extract file IDs from attachment metadata.

    Args:
        attachments_meta: List of attachment metadata dictionaries

    Returns:
        Set of file IDs
    """
    file_ids: Set[str] = set()

    for att in attachments_meta:
        fid = att.get("id")
        if isinstance(fid, str):
            file_ids.add(fid)

    return file_ids
