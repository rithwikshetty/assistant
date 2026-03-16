import json

from app.chat.services.history_formatter import format_openai_history


def test_file_read_history_sanitizes_inline_image_bytes_and_keeps_file_reference() -> None:
    tool_payload = {
        "file_id": "file_abc123",
        "_content_blocks": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "a" * 9000,
                },
            },
            {
                "type": "text",
                "text": "Image: crane-plan.png",
            },
        ],
    }
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "tool_name": "file_read",
                    "tool_call_id": "call_1",
                    "args": {"file_id": "file_abc123"},
                    "result_type": "json",
                    "result": json.dumps(tool_payload),
                }
            ],
            "metadata": {},
        }
    ]

    formatted = format_openai_history(messages)
    assert formatted and isinstance(formatted[0], dict)
    content = formatted[0].get("content") or []
    assert content and isinstance(content[0], dict)
    summary_text = str(content[0].get("text") or "")
    assert '"file_id": "file_abc123"' in summary_text
    assert "image_omitted" in summary_text
    assert "\"data\"" not in summary_text
