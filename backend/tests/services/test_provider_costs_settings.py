from decimal import Decimal

import pytest

from app.config.settings import settings
from app.services.provider_costs import (
    estimate_duration_cost,
    estimate_usage_cost,
    invalidate_pricing_cache,
    resolve_pricing,
)


@pytest.fixture(autouse=True)
def _reset_pricing_cache_between_tests():
    invalidate_pricing_cache()
    yield
    invalidate_pricing_cache()


def test_model_pricing_override_updates_existing_model_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "model_pricing_overrides",
        {
            "openai:gpt-4.1": {
                "input_price": "5.0",
                "cache_creation_price": "5.0",
                "cache_read_price": "0.75",
                "output_price": "9.0",
            }
        },
        raising=False,
    )
    monkeypatch.setattr(settings, "duration_pricing_overrides", {}, raising=False)
    invalidate_pricing_cache()

    pricing = resolve_pricing("openai", "gpt-4.1", allow_fallback=False)
    assert pricing is not None
    assert pricing.standard.input_price == Decimal("5.0")
    assert pricing.standard.output_price == Decimal("9.0")

    cost = estimate_usage_cost(
        provider="openai",
        model_name="gpt-4.1",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        total_tokens=2_000_000,
        allow_fallback=False,
    )
    assert cost == Decimal("14.0")


def test_model_pricing_override_allows_new_model_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "model_pricing_overrides",
        {
            "openai:gpt-custom": {
                "input_price": "1.0",
                "cache_creation_price": "1.0",
                "cache_read_price": "0.1",
                "output_price": "2.0",
            }
        },
        raising=False,
    )
    monkeypatch.setattr(settings, "duration_pricing_overrides", {}, raising=False)
    invalidate_pricing_cache()

    pricing = resolve_pricing("openai", "gpt-custom-2026-01", allow_fallback=False)
    assert pricing is not None
    assert pricing.provider == "openai"
    assert pricing.matches("gpt-custom-2026-01")


def test_duration_pricing_override_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "model_pricing_overrides", {}, raising=False)
    monkeypatch.setattr(
        settings,
        "duration_pricing_overrides",
        {"openai:gpt-4o-mini-transcribe": "0.50"},
        raising=False,
    )
    invalidate_pricing_cache()

    cost = estimate_duration_cost(
        provider="openai",
        model_name="gpt-4o-mini-transcribe",
        duration_seconds=2,
    )
    assert cost == Decimal("1.00")
