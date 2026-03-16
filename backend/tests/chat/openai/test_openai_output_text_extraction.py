from app.chat.openai_model import openai_model


def test_extract_text_from_response_payload_message_blocks() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "Hello"},
                    {"type": "output_text", "text": " world"},
                ],
            }
        ]
    }

    assert openai_model._extract_text_from_response_payload(payload) == "Hello world"


def test_extract_text_from_response_payload_direct_text_items() -> None:
    payload = {
        "output": [
            {"type": "output_text", "text": "One"},
            {"type": "text", "text": " two"},
        ]
    }

    assert openai_model._extract_text_from_response_payload(payload) == "One two"


def test_extract_text_from_response_payload_handles_missing_output() -> None:
    assert openai_model._extract_text_from_response_payload({"id": "resp_1"}) == ""
