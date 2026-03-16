import pytest

from app.chat.usage_calculator import resolve_context_window
from app.services.chat_provider_service import (
    chat_model_options,
    provider_for_model,
    validate_chat_model,
)
from app.services.model_buckets import PRIMARY_MODEL_ORDER, normalize_runtime_bucket
from app.services.provider_costs import resolve_pricing


def test_chat_model_options_expose_new_openai_key() -> None:
    assert chat_model_options() == ("gpt-5.4",)


def test_validate_chat_model_accepts_current_keys_and_rejects_removed_aliases() -> None:
    assert validate_chat_model("gpt-5.4") == "gpt-5.4"
    assert validate_chat_model("gpt-5.4-2026-03-01") == "gpt-5.4"

    with pytest.raises(ValueError):
        validate_chat_model("gpt-5.2")

    with pytest.raises(ValueError):
        validate_chat_model("azure-gpt-5.4")


def test_provider_for_model_routes_from_canonical_keys() -> None:
    assert provider_for_model("gpt-5.4") == "openai"


def test_context_window_supports_gpt_5_4_family() -> None:
    assert resolve_context_window("gpt-5.4") == 1_050_000
    assert resolve_context_window("gpt-5.4-2026-03-01") == 1_050_000
    assert resolve_context_window("gpt-5.2") is None


def test_pricing_resolution_uses_gpt_5_4_prefix() -> None:
    openai_pricing = resolve_pricing("openai", "gpt-5.4-2026-03-01")
    assert openai_pricing is not None
    assert openai_pricing.provider == "openai"
    assert openai_pricing.matches("gpt-5.4")


def test_runtime_bucket_order_and_normalization_use_new_openai_family() -> None:
    assert PRIMARY_MODEL_ORDER == ("gpt-5.4",)
    assert normalize_runtime_bucket(None, "gpt-5.4-2026-03-01") == "gpt-5.4"
