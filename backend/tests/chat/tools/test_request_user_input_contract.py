import asyncio

import pytest

from app.chat.tool_definitions import get_openai_tool_specs
from app.chat.toolkit import execute_tool


def test_request_user_input_schema_requires_option_descriptions() -> None:
    specs = get_openai_tool_specs()
    request_spec = next(spec for spec in specs if spec.get("name") == "request_user_input")

    options_schema = (
        request_spec["parameters"]["properties"]["questions"]["items"]["properties"]["options"]["items"]
    )
    assert options_schema["required"] == ["label", "description"]
    assert options_schema["properties"]["description"]["type"] == "string"
    assert options_schema["properties"]["description"]["maxLength"] == 160


def test_request_user_input_toolkit_keeps_option_descriptions() -> None:
    async def _run() -> None:
        result = await execute_tool(
            name="request_user_input",
            arguments={
                "title": "Need a quick decision",
                "prompt": "Choose one path so I can continue.",
                "questions": [
                    {
                        "id": "next_step",
                        "question": "What should we do first?",
                        "options": [
                            {
                                "label": "Ship a small patch",
                                "description": "Fastest path with low risk and limited scope.",
                            },
                            {
                                "label": "Refactor first",
                                "description": "Longer upfront work but improves long-term maintainability.",
                            },
                        ],
                    }
                ],
            },
            context={},
        )

        assert result["request"]["tool"] == "request_user_input"
        options = result["request"]["questions"][0]["options"]
        assert options[0]["description"] == "Fastest path with low risk and limited scope."
        assert options[1]["description"] == "Longer upfront work but improves long-term maintainability."

    asyncio.run(_run())


def test_request_user_input_toolkit_rejects_missing_option_description() -> None:
    async def _run() -> None:
        with pytest.raises(ValueError, match="request_user_input option.description is required"):
            await execute_tool(
                name="request_user_input",
                arguments={
                    "title": "Need a quick decision",
                    "prompt": "Choose one path so I can continue.",
                    "questions": [
                        {
                            "id": "next_step",
                            "question": "What should we do first?",
                            "options": [
                                {"label": "Ship a small patch"},
                                {
                                    "label": "Refactor first",
                                    "description": "Longer upfront work but improves long-term maintainability.",
                                },
                            ],
                        }
                    ],
                },
                context={},
            )

    asyncio.run(_run())
