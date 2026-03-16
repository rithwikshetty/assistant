"""Service for generating follow-up suggestions using OpenAI."""

import json
import logging
from time import perf_counter
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI

from ...config.settings import settings
from ...logging import log_event
from ...services.model_usage_tracker import (
    extract_openai_response_usage,
    record_estimated_model_usage,
)

logger = logging.getLogger(__name__)

FALLBACK_SUGGESTIONS = [
    "Can you explain more about this?",
    "What else should I know?",
    "How can I apply this?",
]

_SUGGESTIONS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
        }
    },
    "required": ["suggestions"],
}


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


async def generate_suggestions(
    conversation_history: List[Dict[str, Any]],
    project_context: Optional[str] = None,
    *,
    analytics_context: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Generate 3 suggested follow-up replies based on conversation context.

    Suggestions adapt to conversational state — answers when the assistant is
    asking the user something, follow-up questions when the assistant provided
    information.

    Args:
        conversation_history: Full conversation messages (role + content).
        project_context: Optional project name for better suggestions.

    Returns:
        List of 3 suggested replies as strings.
    """
    if not settings.openai_api_key:
        return FALLBACK_SUGGESTIONS

    analytics_context = analytics_context or {}

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        started_at = perf_counter()
        model_name = "gpt-4.1"

        project_line = f"\nProject: {project_context}\n" if project_context else ""

        system_prompt = f"""You generate 3 suggested replies that a USER would naturally send next in this conversation.

These are things the USER would type to the AI assistant — written from the user's perspective.

Context: Collaborative AI workspace{project_line}

First, read the assistant's last message carefully and determine the conversational state:

STATE A — The assistant is ASKING the user something (questions, multiple choice, requesting a decision or input):
  → Suggestions should be plausible ANSWERS or responses to what the assistant asked
  → Match the format the assistant expects (e.g. if it asks for "1D / 2B / 3A", suggest answers in that format)
  → Offer different reasonable answer combinations or stances the user might take
  → One suggestion can be a clarification request if the questions are complex

STATE B — The assistant PROVIDED information, analysis, or completed a task:
  → Suggestions should be follow-up questions grounded in specific details from the response
  → Reference actual names, values, standards, or methods mentioned — never be vague
  → Each should serve a different purpose: dig deeper into a specific point, explore a related angle, or move toward practical application

General rules:
- Always match the tone and specificity of the conversation
- Never generate generic suggestions like "Can you explain more?" or "What else should I know?"
- Keep suggestions natural and conversational

Respond with JSON: {{"suggestions": ["suggestion1", "suggestion2", "suggestion3"]}}"""

        input_items: List[Dict[str, Any]] = []
        for msg in conversation_history:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            else:
                text = content
            if role in ("user", "assistant") and text:
                input_items.append({"role": role, "content": str(text)})

        if not input_items:
            return FALLBACK_SUGGESTIONS

        response = await client.responses.create(
            model=model_name,
            store=False,
            instructions=system_prompt,
            input=input_items,
            max_output_tokens=300,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "followup_suggestions",
                    "schema": _SUGGESTIONS_SCHEMA,
                    "strict": True,
                }
            },
        )
        usage = extract_openai_response_usage(response)
        cost = record_estimated_model_usage(
            provider="openai",
            model_name=model_name,
            operation_type="suggestion_generation",
            usage=usage,
            analytics_context=analytics_context,
            db=analytics_context.get("db"),
            latency_ms=max(0, int((perf_counter() - started_at) * 1000)),
        )

        result = json.loads(_extract_output_text(response) or "{}")
        suggestions = result.get("suggestions", [])

        if isinstance(suggestions, list) and len(suggestions) >= 3:
            clean = [s.strip() for s in suggestions if isinstance(s, str) and s.strip()]
            if len(clean) >= 3:
                log_event(
                    logger,
                    "INFO",
                    "chat.suggestions.generated",
                    "final",
                    suggestion_count=len(clean),
                    provider="openai",
                    model=model_name,
                    input_tokens=int(usage.get("input_tokens", 0) or 0),
                    output_tokens=int(usage.get("output_tokens", 0) or 0),
                    total_tokens=int(usage.get("total_tokens", 0) or 0),
                    cost_usd=float(cost),
                )
                return clean[:3]

        log_event(
            logger,
            "WARNING",
            "chat.suggestions.invalid_response",
            "retry",
            payload_type=type(suggestions).__name__,
        )
        return FALLBACK_SUGGESTIONS

    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "chat.suggestions.failed",
            "error",
            error_type=type(exc).__name__,
            exc_info=True,
        )
        return FALLBACK_SUGGESTIONS
