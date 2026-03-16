from app.chat.tool_payload_sanitizer import (
    sanitize_tool_payload_for_model,
    sanitize_tool_payload_for_storage,
)


def test_non_dict_payload_is_passthrough() -> None:
    text_payload = "plain-text-payload"
    assert sanitize_tool_payload_for_model("request_user_input", text_payload) == text_payload
    assert sanitize_tool_payload_for_storage("request_user_input", text_payload) == text_payload


def test_file_read_sanitizer_omits_inline_image_bytes() -> None:
    payload = {
        "file_id": "file_789",
        "_content_blocks": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "a" * 12000,
                },
            },
            {
                "type": "text",
                "text": "Image: generated.png",
            },
        ],
    }

    sanitized = sanitize_tool_payload_for_model("file_read", payload)

    assert isinstance(sanitized, dict)
    assert sanitized.get("file_id") == "file_789"
    assert sanitized.get("image_context_note")
    blocks = sanitized.get("_content_blocks")
    assert isinstance(blocks, list)
    assert len(blocks) == 2
    assert blocks[0].get("type") == "image_omitted"
    assert "data" not in str(blocks[0])
