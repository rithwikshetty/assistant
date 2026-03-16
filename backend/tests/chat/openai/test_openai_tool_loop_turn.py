import asyncio
import json

from app.chat.openai_model.tool_loop import execute_openai_tool_loop_turn


def test_openai_tool_loop_turn_executes_calls_and_builds_next_items() -> None:
    async def _run() -> None:
        tool_calls = [
            {
                "id": "item_1",
                "call_id": "call_1",
                "name": "retrieval_web_search",
                "arguments": json.dumps({"query": "steel rates"}),
            },
            {
                "id": "item_2",
                "call_id": "call_2",
                "name": "execute_code",
                "arguments": "{not-json",
            },
        ]

        execute_calls = []

        async def _fake_execute_tool(*, name, arguments, context):
            execute_calls.append((name, arguments, context))
            return {"status": "ok", "tool": name}

        outcome = await execute_openai_tool_loop_turn(
            tool_calls=tool_calls,
            tool_context={"conversation_id": "conv_1"},
            execute_tool_fn=_fake_execute_tool,
        )

        assert len(execute_calls) == 1
        assert execute_calls[0][0] == "retrieval_web_search"
        assert execute_calls[0][1] == {"query": "steel rates"}

        emitted_types = [event.get("type") for event in outcome.emitted_events]
        assert emitted_types == ["tool_arguments", "tool_query", "tool_error", "tool_result"]

        assert outcome.await_user_input_event is None
        assert len(outcome.tool_results) == 2
        assert len(outcome.next_items) == 4
        assert [item.get("type") for item in outcome.next_items[:2]] == ["function_call", "function_call"]
        assert [item.get("type") for item in outcome.next_items[2:]] == [
            "function_call_output",
            "function_call_output",
        ]

        assert outcome.tool_execution_structure is not None
        assert outcome.tool_execution_structure["type"] == "tool_execution_structure"
        assert len(outcome.tool_execution_structure["assistant_blocks"]) == 2
        assert len(outcome.tool_execution_structure["user_blocks"]) == 2

    asyncio.run(_run())


def test_openai_tool_loop_turn_emits_await_user_input_and_stops_next_items() -> None:
    async def _run() -> None:
        tool_calls = [
            {
                "id": "item_1",
                "call_id": "call_1",
                "name": "request_user_input",
                "arguments": json.dumps({"title": "Need info"}),
            }
        ]

        async def _fake_execute_tool(*, name, arguments, context):
            _ = name
            _ = arguments
            _ = context
            return {
                "status": "pending",
                "interaction_type": "user_input",
                "request": {"title": "Need info"},
            }

        outcome = await execute_openai_tool_loop_turn(
            tool_calls=tool_calls,
            tool_context={},
            execute_tool_fn=_fake_execute_tool,
        )

        assert [event.get("type") for event in outcome.emitted_events] == ["tool_arguments", "tool_result"]
        assert outcome.await_user_input_event is not None
        assert outcome.await_user_input_event.get("type") == "await_user_input"
        pending_requests = outcome.await_user_input_event.get("content", {}).get("pending_requests", [])
        assert len(pending_requests) == 1
        assert pending_requests[0]["tool_name"] == "request_user_input"
        assert outcome.next_items == []
        assert outcome.tool_execution_structure is None

    asyncio.run(_run())


def test_openai_tool_loop_turn_surfaces_tool_exceptions_as_tool_error() -> None:
    async def _run() -> None:
        tool_calls = [
            {
                "id": "item_1",
                "call_id": "call_1",
                "name": "retrieval_project_files",
                "arguments": json.dumps({"query": "cost plan"}),
            }
        ]

        async def _fake_execute_tool(*, name, arguments, context):
            _ = name
            _ = arguments
            _ = context
            raise RuntimeError("tool exploded")

        outcome = await execute_openai_tool_loop_turn(
            tool_calls=tool_calls,
            tool_context={},
            execute_tool_fn=_fake_execute_tool,
        )

        assert [event.get("type") for event in outcome.emitted_events] == ["tool_arguments", "tool_query", "tool_error"]
        assert outcome.await_user_input_event is None
        assert len(outcome.tool_results) == 1
        assert outcome.tool_results[0].get("status") == "error"
        assert len(outcome.next_items) == 2
        assert outcome.next_items[0]["type"] == "function_call"
        assert outcome.next_items[1]["type"] == "function_call_output"
        parsed_output = json.loads(outcome.next_items[1]["output"])
        assert parsed_output["status"] == "error"
        assert parsed_output["error"]["message"] == "tool exploded"

    asyncio.run(_run())


def test_openai_tool_loop_turn_dedupes_identical_tool_invocations() -> None:
    async def _run() -> None:
        tool_calls = [
            {
                "id": "item_1",
                "call_id": "call_1",
                "name": "calc_basic",
                "arguments": json.dumps({"expression": "2+2"}),
            },
            {
                "id": "item_2",
                "call_id": "call_2",
                "name": "calc_basic",
                "arguments": json.dumps({"expression": "2+2"}),
            },
        ]

        execute_calls = []

        async def _fake_execute_tool(*, name, arguments, context):
            execute_calls.append((name, arguments, context))
            return {"value": 4}

        outcome = await execute_openai_tool_loop_turn(
            tool_calls=tool_calls,
            tool_context={"conversation_id": "conv_dedupe"},
            execute_tool_fn=_fake_execute_tool,
        )

        assert len(execute_calls) == 1
        assert execute_calls[0][0] == "calc_basic"
        assert execute_calls[0][1] == {"expression": "2+2"}

        assert [row.get("status") for row in outcome.tool_results] == ["ok", "ok"]
        call_ids = [row.get("call_id") for row in outcome.tool_results]
        assert set(call_ids) == {"call_1", "call_2"}

        function_outputs = [item for item in outcome.next_items if item.get("type") == "function_call_output"]
        assert len(function_outputs) == 2
        assert {item.get("call_id") for item in function_outputs} == {"call_1", "call_2"}

    asyncio.run(_run())


def test_openai_tool_loop_turn_dedupes_pending_user_input_requests() -> None:
    async def _run() -> None:
        tool_calls = [
            {
                "id": "item_1",
                "call_id": "call_1",
                "name": "request_user_input",
                "arguments": json.dumps({"title": "Need details"}),
            },
            {
                "id": "item_2",
                "call_id": "call_2",
                "name": "request_user_input",
                "arguments": json.dumps({"title": "Need details"}),
            },
        ]

        execute_calls = []

        async def _fake_execute_tool(*, name, arguments, context):
            execute_calls.append((name, arguments, context))
            return {
                "status": "pending",
                "interaction_type": "user_input",
                "request": {"title": "Need details"},
            }

        outcome = await execute_openai_tool_loop_turn(
            tool_calls=tool_calls,
            tool_context={},
            execute_tool_fn=_fake_execute_tool,
        )

        assert len(execute_calls) == 1
        assert outcome.await_user_input_event is not None
        pending_requests = outcome.await_user_input_event.get("content", {}).get("pending_requests", [])
        assert len(pending_requests) == 1
        assert outcome.next_items == []
        assert len(outcome.tool_results) == 1

    asyncio.run(_run())


def test_openai_tool_loop_turn_retries_sparse_chart_with_filtered_data() -> None:
    async def _run() -> None:
        tool_calls = [
            {
                "id": "item_1",
                "call_id": "call_chart_1",
                "name": "viz_create_chart",
                "arguments": json.dumps(
                    {
                        "type": "line",
                        "title": "Branch rate by day",
                        "x_axis_key": "date",
                        "data_keys": ["branch_rate"],
                        "data": [
                            {"date": "2026-02-01", "branch_rate": 0},
                            {"date": "2026-02-02", "branch_rate": 0},
                            {"date": "2026-02-03", "branch_rate": 0.1111},
                        ],
                    }
                ),
            }
        ]

        execute_args = []

        async def _fake_execute_tool(*, name, arguments, context):
            _ = context
            execute_args.append((name, arguments))
            if len(execute_args) == 1:
                raise RuntimeError("Sparse data: Only 1 out of 3 categories have values.")
            return {
                "type": "line",
                "title": "Branch rate by day",
                "data": arguments.get("data"),
                "config": {"x_axis_key": "date", "data_keys": ["branch_rate"]},
            }

        outcome = await execute_openai_tool_loop_turn(
            tool_calls=tool_calls,
            tool_context={},
            execute_tool_fn=_fake_execute_tool,
        )

        assert len(execute_args) == 2
        assert execute_args[0][0] == "viz_create_chart"
        assert execute_args[1][0] == "viz_create_chart"
        assert len(execute_args[1][1]["data"]) == 1
        assert execute_args[1][1]["data"][0]["date"] == "2026-02-03"

        assert [event.get("type") for event in outcome.emitted_events] == ["tool_arguments", "tool_result"]
        assert outcome.tool_results[0]["status"] == "ok"
        result_payload = outcome.tool_results[0]["result"]
        assert isinstance(result_payload, dict)
        assert result_payload.get("auto_retry", {}).get("attempted") is True

    asyncio.run(_run())
