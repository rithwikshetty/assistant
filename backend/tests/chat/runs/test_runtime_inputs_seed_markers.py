from app.chat.run_engine.runtime_inputs import RunInputPreparer


def test_seed_from_activity_rows_maps_tool_reasoning_and_compaction_items() -> None:
    preparer = RunInputPreparer()

    activity_rows = [
        {
            "kind": "tool",
            "sequence": 4,
            "title": "retrieval_web_search",
            "payload": {
                "tool_call_id": "call_1",
                "tool_name": "retrieval_web_search",
                "position": 18,
                "arguments": {"query": "iran war"},
                "result": {"status": "completed", "count": 4},
            },
        },
        {
            "kind": "reasoning",
            "sequence": 6,
            "title": "Thinking",
            "payload": {
                "id": "reasoning_1",
                "title": "Thinking",
                "position": 41,
                "raw_text": "Checking sources",
            },
        },
        {
            "kind": "compaction",
            "sequence": 8,
            "title": "Automatically compacting context",
            "payload": {
                "item_id": "cmp_1",
                "label": "Automatically compacting context",
                "position": 77,
                "source": "openai_server",
            },
        },
    ]

    tool_markers, reasoning_summaries, compaction_markers = preparer._seed_from_activity_rows(activity_rows)

    assert tool_markers == [
        {
            "name": "retrieval_web_search",
            "call_id": "call_1",
            "pos": 18,
            "seq": 4,
            "arguments": {"query": "iran war"},
            "result": {"status": "completed", "count": 4},
        }
    ]
    assert reasoning_summaries == [
        {
            "title": "Thinking",
            "raw_text": "Checking sources",
            "position": 41,
            "sequence": 6,
            "id": "reasoning_1",
        }
    ]
    assert compaction_markers == [
        {
            "pos": 77,
            "seq": 8,
            "label": "Automatically compacting context",
            "item_id": "cmp_1",
            "source": "openai_server",
        }
    ]
