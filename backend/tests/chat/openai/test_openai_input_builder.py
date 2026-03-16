from app.chat.openai_model import input_builder


def test_coerce_system_instructions_from_block_list() -> None:
    instructions = input_builder.coerce_system_instructions(
        [
            {"type": "text", "text": "  First rule  "},
            {"type": "text", "text": "Second rule"},
            {"type": "text", "text": "   "},
        ]
    )
    assert instructions == "First rule\n\nSecond rule"


def test_build_input_from_history_keeps_multimodal_and_prefixes_user_query() -> None:
    history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "History text"},
                {"type": "image", "source": {"type": "url", "url": "https://img.example/1.png"}},
            ],
        }
    ]

    query = [{"type": "text", "text": "Current question"}]
    built = input_builder.build_input_from_history(history, query, "Context prefix")

    assert built[0]["role"] == "user"
    assert built[0]["content"] == [
        {"type": "input_text", "text": "History text"},
        {"type": "input_image", "image_url": "https://img.example/1.png"},
    ]
    assert built[1]["role"] == "user"
    assert built[1]["content"][0] == {"type": "input_text", "text": "Context prefix"}
    assert built[1]["content"][1] == {"type": "input_text", "text": "Current question"}


def test_strip_session_context_messages_removes_string_and_structured_user_messages() -> None:
    prefix = "[Session context — summary of actions completed before context compaction]"
    items = [
        {"role": "user", "content": f"{prefix}\nFiles already read: spec.pdf"},
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": f"{prefix}\nWeb searches completed: foo"}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "output_text", "text": f"{prefix}\nCalculations performed: calc_tax"}],
        },
        {"role": "user", "content": [{"type": "input_text", "text": "Keep this real user text"}]},
        {"role": "assistant", "content": f"{prefix}\nAssistant content should not be stripped"},
    ]

    stripped = input_builder.strip_session_context_messages(items)

    assert len(stripped) == 2
    assert stripped[0]["role"] == "user"
    assert stripped[1]["role"] == "assistant"
