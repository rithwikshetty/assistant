from app.chat.streaming_helpers import StreamingHelpersMixin
from app.chat.streaming_support import StreamState
from app.chat.usage_calculator import RawUsageSummary


class _StreamingHelperHarness(StreamingHelpersMixin):
    pass


class _NoUsageCalculator:
    def summarize(self, raw_responses, provider):  # type: ignore[no-untyped-def]
        del raw_responses, provider
        return RawUsageSummary(
            total_input=0,
            total_output=0,
            context_input=None,
            context_output=None,
            context_total=None,
            base_input=None,
            cache_creation_input=None,
            cache_read_input=None,
            reasoning_output=None,
            saw_usage=False,
        )

    def resolve_context_window(self, model_name):  # type: ignore[no-untyped-def]
        del model_name
        return 1_050_000


class _ProviderUsageCalculator:
    def summarize(self, raw_responses, provider):  # type: ignore[no-untyped-def]
        del raw_responses, provider
        return RawUsageSummary(
            total_input=1200,
            total_output=300,
            context_input=1200,
            context_output=300,
            context_total=1500,
            base_input=1200,
            cache_creation_input=0,
            cache_read_input=0,
            reasoning_output=0,
            saw_usage=True,
        )

    def resolve_context_window(self, model_name):  # type: ignore[no-untyped-def]
        del model_name
        return 1_050_000

    def build_usage_payload(self, summary, context_window):  # type: ignore[no-untyped-def]
        del summary, context_window
        return {
            "input_tokens": 1200,
            "output_tokens": 300,
            "total_tokens": 1500,
            "max_context_tokens": 1_050_000,
            "remaining_context_tokens": 1_048_500,
        }

    def create_conversation_usage(self, existing_metadata, usage_payload, context_window):  # type: ignore[no-untyped-def]
        del existing_metadata, context_window
        return dict(usage_payload), {}


def test_live_conversation_usage_event_requires_provider_usage() -> None:
    helper = _StreamingHelperHarness()
    event = helper._build_live_conversation_usage_event(
        state=StreamState(),
        usage_calculator=_NoUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        fallback_model="gpt-5.4",
        base_conversation_metadata={},
    )

    assert event is None


def test_live_conversation_usage_event_marks_provider_source() -> None:
    helper = _StreamingHelperHarness()
    event = helper._build_live_conversation_usage_event(
        state=StreamState(),
        usage_calculator=_ProviderUsageCalculator(),  # type: ignore[arg-type]
        provider_name="openai",
        fallback_model="gpt-5.4",
        base_conversation_metadata={},
    )

    assert event is not None
    assert event["type"] == "conversation_usage"
    assert event["data"]["source"] == "provider"
    assert event["data"]["conversationUsage"]["total_tokens"] == 1500


def test_token_count_conversation_usage_event_marks_token_count_source() -> None:
    helper = _StreamingHelperHarness()
    event = helper._build_token_count_conversation_usage_event(
        input_tokens=321,
        usage_calculator=_NoUsageCalculator(),  # type: ignore[arg-type]
        model_name="gpt-5.4",
    )

    assert event is not None
    assert event["type"] == "conversation_usage"
    assert event["data"]["source"] == "token_count"
    assert event["data"]["usage"] == {
        "input_tokens": 321,
        "total_tokens": 321,
    }
    assert event["data"]["conversationUsage"]["input_tokens"] == 321
    assert event["data"]["conversationUsage"]["total_tokens"] == 321
