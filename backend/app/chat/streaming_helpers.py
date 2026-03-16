from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..config.settings import settings
from ..database.models import User
from ..logging import log_event
from ..services.chat_provider_service import resolve_chat_provider_for_user_async
from .streaming_support import StreamState
from .usage_calculator import DEFAULT_CONTEXT_WINDOW, UsageCalculator

logger = logging.getLogger(__name__)


class StreamingHelpersMixin:
    """Shared helper methods extracted from ChatStreamingManager for readability."""

    @staticmethod
    def _enqueue_sector_classification(conversation_id: str) -> None:
        """Sector analytics are disabled in the open-source build."""
        log_event(
            logger,
            "DEBUG",
            "sector.classify.skipped",
            "timing",
            conversation_id=conversation_id,
        )

    @staticmethod
    def _coerce_metadata_dict(raw_metadata: Any) -> Dict[str, Any]:
        """Normalize conversation metadata into a mutable dict."""
        if isinstance(raw_metadata, dict):
            try:
                return dict(raw_metadata)
            except Exception:
                return {}
        if isinstance(raw_metadata, str):
            text = raw_metadata.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return dict(parsed)
            except Exception:
                return {}
        return {}

    @staticmethod
    def _resolve_model_from_raw_responses(
        raw_responses: List[Dict[str, Any]],
        fallback_model: str,
    ) -> str:
        for raw in reversed(raw_responses):
            if not isinstance(raw, dict):
                continue
            candidate_model = raw.get("model")
            if isinstance(candidate_model, str) and candidate_model.strip():
                return candidate_model.strip()
        return fallback_model

    @staticmethod
    def _resolve_display_context_window(
        *,
        usage_calculator: UsageCalculator,
        model_name: Optional[str],
    ) -> int:
        """Resolve the UI context window override/fallback consistently with finalization."""
        actual_context_window = usage_calculator.resolve_context_window(model_name)
        try:
            if settings.display_context_window_tokens is not None:
                return int(settings.display_context_window_tokens)
        except Exception:
            pass
        return int(actual_context_window or DEFAULT_CONTEXT_WINDOW)

    @staticmethod
    def _live_usage_signature(event_payload: Dict[str, Any]) -> str:
        """Stable fingerprint used to suppress duplicate live usage events."""
        try:
            return json.dumps(event_payload, sort_keys=True, default=str)
        except Exception:
            return str(event_payload)

    def _build_live_conversation_usage_event(
        self,
        *,
        state: StreamState,
        usage_calculator: UsageCalculator,
        provider_name: str,
        fallback_model: str,
        base_conversation_metadata: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Build an in-stream conversation usage snapshot event."""
        summary = usage_calculator.summarize(state.raw_responses, provider=provider_name)
        if not summary.saw_usage:
            return None
        model_for_usage = self._resolve_model_from_raw_responses(
            state.raw_responses,
            fallback_model=fallback_model,
        )
        context_window = self._resolve_display_context_window(
            usage_calculator=usage_calculator,
            model_name=model_for_usage,
        )
        source = "provider"
        usage_payload = usage_calculator.build_usage_payload(summary, context_window)

        conversation_usage_payload, _ = usage_calculator.create_conversation_usage(
            base_conversation_metadata,
            usage_payload,
            context_window,
        )
        if not conversation_usage_payload:
            return None

        return {
            "type": "conversation_usage",
            "data": {
                "source": source,
                "conversationUsage": conversation_usage_payload,
                "usage": usage_payload,
            },
        }

    def _build_token_count_conversation_usage_event(
        self,
        *,
        input_tokens: int,
        usage_calculator: UsageCalculator,
        model_name: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Build a live usage snapshot from token-count API input totals."""
        if input_tokens <= 0:
            return None

        context_window = self._resolve_display_context_window(
            usage_calculator=usage_calculator,
            model_name=model_name,
        )
        remaining = max(0, context_window - input_tokens) if context_window > 0 else 0
        compact_trigger = getattr(settings, "openai_compact_trigger_tokens", None)

        conversation_usage_payload: Dict[str, Any] = {
            "input_tokens": input_tokens,
            "output_tokens": 0,
            "total_tokens": input_tokens,
            "max_context_tokens": context_window,
            "remaining_context_tokens": remaining,
            "current_context_tokens": input_tokens,
            "peak_context_tokens": input_tokens,
        }
        if isinstance(compact_trigger, int) and compact_trigger > 0:
            conversation_usage_payload["compact_trigger_tokens"] = compact_trigger

        return {
            "type": "conversation_usage",
            "data": {
                "source": "token_count",
                "conversationUsage": conversation_usage_payload,
                "usage": {
                    "input_tokens": input_tokens,
                    "total_tokens": input_tokens,
                },
            },
        }

    async def _resolve_provider_and_model(
        self,
        db: AsyncSession,
        user: Optional[User],
    ) -> tuple[str, str, str]:
        """Resolve provider and model for chat runtime.

        Returns: (provider_name, effective_model, reasoning_effort)
        """
        provider_name, effective_model = await resolve_chat_provider_for_user_async(db, user)
        reasoning_effort = settings.chat_reasoning_effort
        return provider_name, effective_model, reasoning_effort
