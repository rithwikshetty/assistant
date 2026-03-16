from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, getcontext
from functools import lru_cache
from typing import Any, Mapping, Optional, Tuple

from ..config.settings import settings

getcontext().prec = 28

_MILLION = Decimal("1000000")


def _to_decimal(value: str | float | int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return Decimal(value)


def _coerce_tokens(value: Optional[int]) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def _coerce_non_negative_decimal(
    value: Any,
    *,
    fallback: Optional[Decimal] = None,
) -> Optional[Decimal]:
    if value is None:
        return fallback
    try:
        parsed = _to_decimal(value)
    except Exception:
        return fallback
    if parsed < 0:
        return fallback
    return parsed


def _coerce_non_negative_int(
    value: Any,
    *,
    fallback: Optional[int] = None,
) -> Optional[int]:
    if value is None:
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    if parsed < 0:
        return fallback
    return parsed


@dataclass(frozen=True)
class PricingTier:
    input_price: Decimal
    cache_creation_price: Decimal
    cache_read_price: Decimal
    output_price: Decimal


@dataclass(frozen=True)
class ModelPricing:
    provider: str
    match_prefixes: Tuple[str, ...]
    standard: PricingTier
    long_context_threshold: Optional[int] = None
    long_context: Optional[PricingTier] = None

    def matches(self, model_name: str) -> bool:
        if not model_name:
            return False
        lowered = model_name.lower()
        return any(lowered.startswith(prefix) for prefix in self.match_prefixes)

    def resolve_tier(self, total_input_tokens: int) -> PricingTier:
        if (
            self.long_context_threshold is not None
            and self.long_context is not None
            and total_input_tokens > self.long_context_threshold
        ):
            return self.long_context
        return self.standard


_OPENAI_GPT_5_4 = ModelPricing(
    provider="openai",
    match_prefixes=(
        "gpt-5.4",
    ),
    standard=PricingTier(
        # GPT-5.4 pricing per 1M tokens.
        input_price=_to_decimal("2.50"),
        cache_creation_price=_to_decimal("2.50"),
        cache_read_price=_to_decimal("0.25"),
        output_price=_to_decimal("15.00"),
    ),
    # Official GPT-5.4 pricing adds long-context multipliers above 272K input
    # tokens. Cache pricing is inferred to follow the same input multiplier.
    long_context_threshold=272_000,
    long_context=PricingTier(
        input_price=_to_decimal("5.00"),
        cache_creation_price=_to_decimal("5.00"),
        cache_read_price=_to_decimal("0.50"),
        output_price=_to_decimal("22.50"),
    ),
)

_OPENAI_GPT_4_1 = ModelPricing(
    provider="openai",
    match_prefixes=(
        "gpt-4.1",
    ),
    standard=PricingTier(
        # OpenAI GPT-4.1 pricing per 1M tokens.
        input_price=_to_decimal("2.0"),
        cache_creation_price=_to_decimal("2.0"),
        cache_read_price=_to_decimal("0.5"),
        output_price=_to_decimal("8.0"),
    ),
)

_OPENAI_GPT_4_1_MINI = ModelPricing(
    provider="openai",
    match_prefixes=(
        "gpt-4.1-mini",
    ),
    standard=PricingTier(
        # OpenAI GPT-4.1 mini pricing per 1M tokens.
        input_price=_to_decimal("0.4"),
        cache_creation_price=_to_decimal("0.4"),
        cache_read_price=_to_decimal("0.1"),
        output_price=_to_decimal("1.6"),
    ),
)

_OPENAI_GPT_4_1_NANO = ModelPricing(
    provider="openai",
    match_prefixes=(
        "gpt-4.1-nano",
    ),
    standard=PricingTier(
        # OpenAI GPT-4.1 nano pricing per 1M tokens.
        input_price=_to_decimal("0.1"),
        cache_creation_price=_to_decimal("0.1"),
        cache_read_price=_to_decimal("0.025"),
        output_price=_to_decimal("0.4"),
    ),
)

_OPENAI_TEXT_EMBEDDING_3_SMALL = ModelPricing(
    provider="openai",
    match_prefixes=(
        "text-embedding-3-small",
    ),
    standard=PricingTier(
        # OpenAI text-embedding-3-small pricing per 1M input tokens.
        input_price=_to_decimal("0.02"),
        cache_creation_price=_to_decimal("0.02"),
        cache_read_price=_to_decimal("0.0"),
        output_price=_to_decimal("0.0"),
    ),
)

_DEFAULT_MODEL_PRICING: Tuple[ModelPricing, ...] = (
    _OPENAI_GPT_5_4,
    _OPENAI_GPT_4_1_MINI,
    _OPENAI_GPT_4_1_NANO,
    _OPENAI_GPT_4_1,
    _OPENAI_TEXT_EMBEDDING_3_SMALL,
)

_DEFAULT_FALLBACK: dict[str, ModelPricing] = {
    "openai": _OPENAI_GPT_5_4,
}

_DURATION_PRICING_PER_SECOND: Tuple[Tuple[str, str, Decimal], ...] = (
    # OpenAI gpt-4o-mini-transcribe: $0.003 / minute.
    ("openai", "gpt-4o-mini-transcribe", _to_decimal("0.003") / Decimal("60")),
)

_OVERRIDE_KEY_DELIMITER = ":"


def _parse_override_key(raw_key: Any) -> Optional[Tuple[str, str]]:
    key = str(raw_key or "").strip().lower()
    if _OVERRIDE_KEY_DELIMITER not in key:
        return None
    provider, model_prefix = key.split(_OVERRIDE_KEY_DELIMITER, 1)
    provider = provider.strip().lower()
    model_prefix = model_prefix.strip().lower()
    if not provider or not model_prefix:
        return None
    return provider, model_prefix


@lru_cache(maxsize=1)
def _model_pricing_overrides() -> dict[tuple[str, str], dict[str, Any]]:
    raw = getattr(settings, "model_pricing_overrides", {}) or {}
    if not isinstance(raw, dict):
        return {}

    overrides: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_key, payload in raw.items():
        parsed_key = _parse_override_key(raw_key)
        if parsed_key is None or not isinstance(payload, dict):
            continue
        overrides[parsed_key] = dict(payload)
    return overrides


@lru_cache(maxsize=1)
def _duration_pricing_overrides() -> dict[tuple[str, str], Decimal]:
    raw = getattr(settings, "duration_pricing_overrides", {}) or {}
    if not isinstance(raw, dict):
        return {}

    overrides: dict[tuple[str, str], Decimal] = {}
    for raw_key, raw_price in raw.items():
        parsed_key = _parse_override_key(raw_key)
        if parsed_key is None:
            continue
        price = _coerce_non_negative_decimal(raw_price)
        if price is None:
            continue
        overrides[parsed_key] = price
    return overrides


def _resolve_best_model_override(
    *,
    provider: str,
    model_name: str,
) -> Optional[tuple[str, dict[str, Any]]]:
    best_match: Optional[tuple[str, dict[str, Any]]] = None
    best_length = -1

    for (candidate_provider, model_prefix), payload in _model_pricing_overrides().items():
        if provider != candidate_provider:
            continue
        if not model_name.startswith(model_prefix):
            continue
        if len(model_prefix) > best_length:
            best_match = (model_prefix, payload)
            best_length = len(model_prefix)
    return best_match


def _resolve_best_duration_override(
    *,
    provider: str,
    model_name: str,
) -> Optional[Decimal]:
    best_length = -1
    best_value: Optional[Decimal] = None
    for (candidate_provider, model_prefix), price in _duration_pricing_overrides().items():
        if provider != candidate_provider:
            continue
        if not model_name.startswith(model_prefix):
            continue
        if len(model_prefix) > best_length:
            best_length = len(model_prefix)
            best_value = price
    return best_value


def _resolve_price_field(
    payload: Mapping[str, Any],
    *,
    field_name: str,
    fallback: Optional[Decimal],
) -> Optional[Decimal]:
    parsed = _coerce_non_negative_decimal(payload.get(field_name), fallback=fallback)
    return parsed


def _build_tier_from_payload(
    payload: Mapping[str, Any],
    *,
    fallback: Optional[PricingTier],
) -> Optional[PricingTier]:
    input_price = _resolve_price_field(
        payload,
        field_name="input_price",
        fallback=fallback.input_price if fallback else None,
    )
    cache_creation_price = _resolve_price_field(
        payload,
        field_name="cache_creation_price",
        fallback=fallback.cache_creation_price if fallback else None,
    )
    cache_read_price = _resolve_price_field(
        payload,
        field_name="cache_read_price",
        fallback=fallback.cache_read_price if fallback else None,
    )
    output_price = _resolve_price_field(
        payload,
        field_name="output_price",
        fallback=fallback.output_price if fallback else None,
    )

    if (
        input_price is None
        or cache_creation_price is None
        or cache_read_price is None
        or output_price is None
    ):
        return None
    return PricingTier(
        input_price=input_price,
        cache_creation_price=cache_creation_price,
        cache_read_price=cache_read_price,
        output_price=output_price,
    )


def _build_long_context_from_payload(
    payload: Mapping[str, Any],
    *,
    fallback_threshold: Optional[int],
    fallback_tier: Optional[PricingTier],
) -> tuple[Optional[int], Optional[PricingTier]]:
    has_long_override = any(
        key in payload
        for key in (
            "long_context_threshold",
            "long_context_input_price",
            "long_context_cache_creation_price",
            "long_context_cache_read_price",
            "long_context_output_price",
        )
    )
    if not has_long_override:
        return fallback_threshold, fallback_tier

    threshold = _coerce_non_negative_int(
        payload.get("long_context_threshold"),
        fallback=fallback_threshold,
    )
    if threshold is None:
        return None, None

    long_tier_payload = {
        "input_price": payload.get("long_context_input_price"),
        "cache_creation_price": payload.get("long_context_cache_creation_price"),
        "cache_read_price": payload.get("long_context_cache_read_price"),
        "output_price": payload.get("long_context_output_price"),
    }
    long_tier = _build_tier_from_payload(
        long_tier_payload,
        fallback=fallback_tier,
    )
    if long_tier is None:
        return None, None
    return threshold, long_tier


def _apply_override_to_pricing(
    *,
    base_pricing: Optional[ModelPricing],
    provider: str,
    override_model_prefix: str,
    payload: Mapping[str, Any],
) -> Optional[ModelPricing]:
    standard_tier = _build_tier_from_payload(
        payload,
        fallback=base_pricing.standard if base_pricing else None,
    )
    if standard_tier is None:
        return base_pricing

    long_context_threshold, long_context_tier = _build_long_context_from_payload(
        payload,
        fallback_threshold=base_pricing.long_context_threshold if base_pricing else None,
        fallback_tier=base_pricing.long_context if base_pricing else None,
    )

    if base_pricing is not None:
        prefixes = base_pricing.match_prefixes
    else:
        prefixes = (override_model_prefix,)

    return ModelPricing(
        provider=provider,
        match_prefixes=prefixes,
        standard=standard_tier,
        long_context_threshold=long_context_threshold,
        long_context=long_context_tier,
    )


def resolve_pricing(
    provider: Optional[str],
    model_name: Optional[str],
    *,
    allow_fallback: bool = True,
) -> Optional[ModelPricing]:
    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model_name or "").strip().lower()
    if not normalized_provider:
        return None

    matched_pricing: Optional[ModelPricing] = None
    if normalized_model:
        for pricing in _DEFAULT_MODEL_PRICING:
            if pricing.provider == normalized_provider and pricing.matches(normalized_model):
                matched_pricing = pricing
                break

        override = _resolve_best_model_override(
            provider=normalized_provider,
            model_name=normalized_model,
        )
        if override is not None:
            model_prefix, payload = override
            overridden = _apply_override_to_pricing(
                base_pricing=matched_pricing,
                provider=normalized_provider,
                override_model_prefix=model_prefix,
                payload=payload,
            )
            if overridden is not None:
                return overridden
        if matched_pricing is not None:
            return matched_pricing

    if allow_fallback:
        return _DEFAULT_FALLBACK.get(normalized_provider)
    return None


def _resolve_duration_price_per_second(
    *,
    provider: Optional[str],
    model_name: Optional[str],
) -> Optional[Decimal]:
    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model_name or "").strip().lower()
    if not normalized_provider or not normalized_model:
        return None

    override_price = _resolve_best_duration_override(
        provider=normalized_provider,
        model_name=normalized_model,
    )
    if override_price is not None:
        return override_price

    for candidate_provider, candidate_model_prefix, price_per_second in _DURATION_PRICING_PER_SECOND:
        if normalized_provider != candidate_provider:
            continue
        if normalized_model.startswith(candidate_model_prefix):
            return price_per_second
    return None


def compute_message_cost(
    *,
    provider: Optional[str],
    model_name: Optional[str],
    base_input_tokens: Optional[int],
    cache_creation_tokens: Optional[int],
    cache_read_tokens: Optional[int],
    output_tokens: Optional[int],
    effective_input_tokens: Optional[int] = None,
) -> Decimal:
    """Calculate message cost based on token usage.
    
    OpenAI reports `input_tokens` as TOTAL input (including
    cached tokens), with cache counters represented as subsets.
    
    Cost formula:
    - Uncached input: uncached × input_price
    - Cache creation: cache_creation × cache_creation_price
    - Cache read: cache_read × cache_read_price
    - Output: output × output_price
    """
    pricing = resolve_pricing(provider, model_name, allow_fallback=True)
    if pricing is None:
        return Decimal("0")

    cache_creation = _coerce_tokens(cache_creation_tokens)
    cache_read = _coerce_tokens(cache_read_tokens)
    output = _coerce_tokens(output_tokens)

    base_input = _coerce_tokens(base_input_tokens)
    if base_input == 0:
        effective = _coerce_tokens(effective_input_tokens)
        if effective:
            recalculated = effective - cache_creation - cache_read
            if recalculated > 0:
                base_input = recalculated

    # Determine total input for tier selection (for long-context pricing)
    total_input = base_input
    tier = pricing.resolve_tier(total_input)

    # OpenAI input_tokens includes cached tokens, so subtract cache tokens.
    uncached_input = max(0, base_input - cache_creation - cache_read)

    cost = Decimal("0")
    if uncached_input:
        cost += tier.input_price * Decimal(uncached_input) / _MILLION
    if cache_creation:
        cost += tier.cache_creation_price * Decimal(cache_creation) / _MILLION
    if cache_read:
        cost += tier.cache_read_price * Decimal(cache_read) / _MILLION
    if output:
        cost += tier.output_price * Decimal(output) / _MILLION

    return cost


def estimate_usage_cost(
    *,
    provider: Optional[str],
    model_name: Optional[str],
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    total_tokens: Optional[int],
    cache_creation_tokens: Optional[int] = None,
    cache_read_tokens: Optional[int] = None,
    allow_fallback: bool = False,
) -> Decimal:
    pricing = resolve_pricing(provider, model_name, allow_fallback=allow_fallback)
    if pricing is None:
        return Decimal("0")

    input_count = _coerce_tokens(input_tokens)
    output_count = _coerce_tokens(output_tokens)
    total_count = _coerce_tokens(total_tokens)
    if total_count <= 0:
        total_count = max(0, input_count + output_count)

    cache_creation = _coerce_tokens(cache_creation_tokens)
    cache_read = _coerce_tokens(cache_read_tokens)

    tier = pricing.resolve_tier(total_count)
    uncached_input = max(0, input_count - cache_creation - cache_read)

    cost = Decimal("0")
    if uncached_input:
        cost += tier.input_price * Decimal(uncached_input) / _MILLION
    if cache_creation:
        cost += tier.cache_creation_price * Decimal(cache_creation) / _MILLION
    if cache_read:
        cost += tier.cache_read_price * Decimal(cache_read) / _MILLION
    if output_count:
        cost += tier.output_price * Decimal(output_count) / _MILLION
    return cost


def estimate_duration_cost(
    *,
    provider: Optional[str],
    model_name: Optional[str],
    duration_seconds: Optional[float | Decimal],
) -> Decimal:
    if duration_seconds is None:
        return Decimal("0")

    try:
        normalized_seconds = Decimal(str(duration_seconds))
    except Exception:
        return Decimal("0")
    if normalized_seconds <= 0:
        return Decimal("0")

    price_per_second = _resolve_duration_price_per_second(
        provider=provider,
        model_name=model_name,
    )
    if price_per_second is None:
        return Decimal("0")
    return price_per_second * normalized_seconds


def invalidate_pricing_cache() -> None:
    _model_pricing_overrides.cache_clear()
    _duration_pricing_overrides.cache_clear()


def format_cost(value: Decimal, digits: int = 4) -> float:
    if not value:
        return 0.0
    quantize_str = "0." + ("0" * (digits - 1)) + "1"
    rounded = value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
    return float(rounded)


__all__ = [
    "compute_message_cost",
    "estimate_usage_cost",
    "estimate_duration_cost",
    "invalidate_pricing_cache",
    "format_cost",
    "resolve_pricing",
]
