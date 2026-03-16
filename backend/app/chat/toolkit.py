"""Tool orchestration for chat streaming.

NOTE FOR AGENTS / DEVELOPERS:
When adding a new tool, also add a user-friendly label in the frontend at:
    frontend/lib/chat/tool-labels.ts
That file maps raw tool names (e.g. "retrieval_web_search") to display labels
(e.g. "Searching the web") shown in the streaming step indicator. Without an
entry there, the raw tool name will be shown to the user as a fallback.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from ..config.database import SessionLocal
from .interactive_tools import INTERACTION_TYPE_USER_INPUT
from .tools.calculations import CALCULATION_TOOL_NAMES, execute_calculation_tool
from .tools.web_search import web_search
from .tools.file_tools import (
    execute_read_uploaded_file,
    execute_search_project_files,
)
from .tools.skills import execute_load_skill
from .tools.visualization import execute_create_chart
from .tools.tasks import execute_tasks
from .tools.code_execution import execute_code_tool


_TOOLS_REQUIRING_DB = {
    "file_read",
    "load_skill",
    "execute_code",
}

_REQUEST_USER_INPUT_OPTION_LABEL_MAX_LENGTH = 80
_REQUEST_USER_INPUT_OPTION_DESCRIPTION_MAX_LENGTH = 160


def _needs_tool_db_session(name: str) -> bool:
    return name in _TOOLS_REQUIRING_DB


async def _execute_tool_impl(
    *,
    name: str,
    arguments: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    yield_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute a shared tool call using the orchestrator tooling."""

    context = context or {}

    if name == "retrieval_web_search":
        query = _require_str(arguments.get("query"), "retrieval_web_search requires a query")
        if yield_fn:
            yield_fn({"type": "tool_query", "name": name, "content": query})
        result = await asyncio.to_thread(web_search, query)
        return {
            "query": query,  # Include query for frontend display
            "content": result.get("content", ""),
            "citations": result.get("citations", []),
            "search_engine": "openai",
        }

    if name == "retrieval_project_files":
        return await execute_search_project_files(arguments, context, yield_fn)

    if name == "file_read":
        return await execute_read_uploaded_file(arguments, context, yield_fn)

    if name == "load_skill":
        return await execute_load_skill(arguments, context, yield_fn)

    if name in CALCULATION_TOOL_NAMES:
        return execute_calculation_tool(name, arguments)

    # Tasks tool (unified)
    if name == "tasks":
        return await execute_tasks(arguments, context, yield_fn)

    if name == "viz_create_chart":
        return execute_create_chart(arguments)

    if name == "viz_create_gantt":
        from .tools.visualization import execute_create_gantt
        return execute_create_gantt(arguments)

    if name == "request_user_input":
        title = _require_str(arguments.get("title"), "request_user_input requires title")
        prompt = _require_str(arguments.get("prompt"), "request_user_input requires prompt")

        submit_label = (
            arguments.get("submit_label").strip()
            if isinstance(arguments.get("submit_label"), str) and arguments.get("submit_label", "").strip()
            else None
        )

        if yield_fn:
            yield_fn({"type": "tool_query", "name": name, "content": "Waiting for user input"})

        questions_raw = arguments.get("questions")
        if not isinstance(questions_raw, list) or not questions_raw:
            raise ValueError("request_user_input requires a non-empty questions array")

        normalized_questions = []
        for raw in questions_raw:
            if not isinstance(raw, dict):
                raise ValueError("request_user_input questions must be objects")
            question_id = _require_str(raw.get("id"), "request_user_input question.id is required")
            question_text = _require_str(raw.get("question"), "request_user_input question.question is required")
            options_raw = raw.get("options")
            if not isinstance(options_raw, list) or len(options_raw) < 2:
                raise ValueError("request_user_input question.options requires at least 2 options")

            normalized_options = []
            for option in options_raw:
                if not isinstance(option, dict):
                    raise ValueError("request_user_input options must be objects")

                option_label = _require_str(option.get("label"), "request_user_input option.label is required")
                if len(option_label) > _REQUEST_USER_INPUT_OPTION_LABEL_MAX_LENGTH:
                    raise ValueError(
                        f"request_user_input option.label must be {_REQUEST_USER_INPUT_OPTION_LABEL_MAX_LENGTH} characters or fewer"
                    )

                option_description = _require_str(
                    option.get("description"),
                    "request_user_input option.description is required",
                )
                if len(option_description) > _REQUEST_USER_INPUT_OPTION_DESCRIPTION_MAX_LENGTH:
                    raise ValueError(
                        f"request_user_input option.description must be {_REQUEST_USER_INPUT_OPTION_DESCRIPTION_MAX_LENGTH} characters or fewer"
                    )

                normalized_options.append(
                    {
                        "label": option_label,
                        "description": option_description,
                    }
                )

            normalized_questions.append(
                {
                    "id": question_id,
                    "question": question_text,
                    "options": normalized_options,
                }
            )

        request_payload = {
            "tool": "request_user_input",
            "title": title,
            "prompt": prompt,
            "questions": normalized_questions,
            "custom_input_label": "Add optional context, links, or constraints",
            "submit_label": submit_label or "Continue",
        }

        return {
            "status": "pending",
            "interaction_type": INTERACTION_TYPE_USER_INPUT,
            "request": request_payload,
        }

    if name == "execute_code":
        return await execute_code_tool(arguments, context, yield_fn)

    raise ValueError(f"Unknown tool: {name}")


async def execute_tool(
    *,
    name: str,
    arguments: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    yield_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Execute a shared tool call with a short-lived DB session when needed."""
    context = context or {}
    scoped_db = None
    if _needs_tool_db_session(name) and context.get("db") is None:
        scoped_db = SessionLocal()
        context = dict(context)
        context["db"] = scoped_db

    try:
        return await _execute_tool_impl(
            name=name,
            arguments=arguments,
            context=context,
            yield_fn=yield_fn,
        )
    finally:
        if scoped_db is not None:
            try:
                scoped_db.close()
            except Exception:
                pass


def _require_str(value: Any, error: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(error)
    return value.strip()
