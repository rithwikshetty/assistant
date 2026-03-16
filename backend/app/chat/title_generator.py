import json
import logging
from time import perf_counter
from typing import Any

from openai import AsyncOpenAI

from ..config.settings import settings
from ..logging import log_event
from ..services.model_usage_tracker import (
    extract_openai_response_usage,
    record_estimated_model_usage,
)

logger = logging.getLogger(__name__)

_openai_async_client: AsyncOpenAI | None = None
_openai_async_client_api_key: str | None = None


_TITLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {
            "type": "string",
            "description": "A short, action-oriented conversation title in sentence case.",
        }
    },
    "required": ["title"],
}

_TITLE_INSTRUCTIONS = (
    'Generate a short, action-oriented title (3-4 words) in British English for this user query. '
    'Start with a verb describing what the user wants to do (for example: "Analyse cost breakdown", '
    '"Organise project files", "Review staged changes", "Investigate process step order"). '
    "Use sentence case and British spelling. Respond with JSON only."
)


def _extract_output_text(response: Any) -> str:
    direct_text = getattr(response, "output_text", None)
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text

    payload = response.model_dump() if hasattr(response, "model_dump") else {}
    if not isinstance(payload, dict):
        return ""

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "").strip().lower() not in {"output_text", "text"}:
                continue
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


def _get_openai_async_client() -> AsyncOpenAI:
    global _openai_async_client, _openai_async_client_api_key

    api_key = (settings.openai_api_key or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured on the server")

    if _openai_async_client is None or _openai_async_client_api_key != api_key:
        _openai_async_client = AsyncOpenAI(api_key=api_key)
        _openai_async_client_api_key = api_key

    return _openai_async_client


async def generate_title(
    user_message: str,
    *,
    analytics_context: dict[str, Any] | None = None,
) -> str:
    """Generate a conversation title from the first user message"""
    if not settings.openai_api_key:
        return "New Chat"

    analytics_context = analytics_context or {}

    try:
        client = _get_openai_async_client()
        started_at = perf_counter()
        model_name = settings.title_generation_model

        response = await client.responses.create(
            model=model_name,
            store=False,
            instructions=_TITLE_INSTRUCTIONS,
            input=user_message,
            max_output_tokens=settings.title_generation_max_tokens,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "conversation_title",
                    "schema": _TITLE_SCHEMA,
                    "strict": True,
                }
            },
        )
        usage = extract_openai_response_usage(response)
        cost = record_estimated_model_usage(
            provider="openai",
            model_name=model_name,
            operation_type="title_generation",
            usage=usage,
            analytics_context=analytics_context,
            db=analytics_context.get("db"),
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
        )

        result = json.loads(_extract_output_text(response) or "{}")
        raw_title = result.get("title", "New Chat")
        title = raw_title.strip() if isinstance(raw_title, str) else "New Chat"
        log_event(
            logger,
            "INFO",
            "chat.title_generation.generated",
            "final",
            provider="openai",
            model=model_name,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            total_tokens=int(usage.get("total_tokens", 0) or 0),
            cost_usd=float(cost),
        )
        return title[0].upper() + title[1:] if title else "New Chat"

    except Exception as exc:
        log_event(
            logger,
            "WARNING",
            "chat.title_generation.failed",
            "retry",
            exc_info=exc,
        )
        return "New Chat"
