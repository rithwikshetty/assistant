from app.chat.openai_model import reasoning


def test_merge_reasoning_summary_text_snapshot_behaviour() -> None:
    combined, delta = reasoning.merge_reasoning_summary_text(
        existing="Step 1",
        incoming="Step 1 and 2",
        treat_as_snapshot=True,
    )
    assert combined == "Step 1 and 2"
    assert delta == " and 2"


def test_append_reasoning_replay_items_deduplicates_by_payload() -> None:
    input_items = [
        {
            "type": "reasoning",
            "encrypted_content": "abc",
            "summary": [{"type": "summary_text", "text": "x"}],
        }
    ]
    replay_items = [
        {
            "type": "reasoning",
            "encrypted_content": "abc",
            "summary": [{"type": "summary_text", "text": "x"}],
        },
        {
            "type": "reasoning",
            "encrypted_content": "def",
            "summary": [],
        },
    ]

    reasoning.append_reasoning_replay_items(input_items, replay_items)

    assert len(input_items) == 2
    assert input_items[-1]["encrypted_content"] == "def"


def test_extract_text_from_response_payload_reads_message_output_text() -> None:
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

    assert reasoning.extract_text_from_response_payload(payload) == "Hello world"
