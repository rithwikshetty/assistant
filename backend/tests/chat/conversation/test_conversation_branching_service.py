from types import SimpleNamespace

from app.chat.services.conversation_branching_service import (
    collect_file_ids_from_messages,
    transform_message_metadata_for_branch,
)
from app.database.models import MessagePart


def _message_with_metadata(payload):
    return SimpleNamespace(parts=[MessagePart(part_type="metadata", payload_jsonb=payload)])


def test_collect_file_ids_from_messages_reads_all_attachment_shapes() -> None:
    messages = [
        _message_with_metadata(
            {
                "attachments": [{"id": "file_a"}, {"id": "file_b"}, {"id": None}],
                "attachment_ids": ["file_c", "", None],
            }
        ),
        _message_with_metadata(
            {
                "attachments": [{"id": "file_b"}, {"id": "file_d"}],
                "attachment_ids": ["file_e"],
            }
        ),
    ]

    assert collect_file_ids_from_messages(messages) == {"file_a", "file_b", "file_c", "file_d", "file_e"}


def test_transform_message_metadata_for_branch_remaps_and_filters_attachments() -> None:
    metadata = {
        "attachments": [
            {"id": "old_1", "name": "A"},
            {"id": "stale_old", "name": "Stale"},
        ],
        "attachment_ids": ["old_1", "stale_old"],
    }
    file_id_map = {"old_1": "new_1"}

    transformed = transform_message_metadata_for_branch(
        metadata,
        file_id_map,
        source_message_id="source_msg_1",
    )

    assert transformed is not None
    assert transformed.get("attachments") == [{"id": "new_1", "name": "A"}]
    assert transformed.get("attachment_ids") == ["new_1"]
    assert transformed.get("source_message_id") == "source_msg_1"
    assert transformed.get("lineage", {}).get("source_message_id") == "source_msg_1"


def test_transform_message_metadata_for_branch_adds_source_message_when_metadata_missing() -> None:
    transformed = transform_message_metadata_for_branch(
        None,
        {},
        source_message_id="source_msg_2",
    )

    assert transformed is not None
    assert transformed.get("source_message_id") == "source_msg_2"
    assert transformed.get("lineage", {}).get("source_message_id") == "source_msg_2"
