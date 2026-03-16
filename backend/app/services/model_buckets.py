from __future__ import annotations

from typing import Optional, Tuple

"""
Helpers for grouping models into runtime buckets for analytics/health.

Key goals:
- Group versioned identifiers into stable families.
- Keep default ordering for primary models while allowing new buckets to
  appear automatically without changing admin/dashboard code.
"""

# Primary families used across the product for ordering and colour mapping.
PRIMARY_MODEL_ORDER: Tuple[str, ...] = (
    "gpt-5.4",
)


def _normalize_family_from_model(model_name: Optional[str]) -> str:
    """
    Return a stable family key for a model identifier.

    Known OpenAI families are normalised to short keys while unknown models
    fall back to their lower-cased identifier.
    """
    raw = (model_name or "").strip().lower()
    if not raw:
        return "unknown"

    # OpenAI GPT‑5.4 family (allow versioned suffixes).
    if raw.startswith("gpt-5.4"):
        return "gpt-5.4"

    # UK OpenAI default model family
    if raw.startswith("gpt-4.1-mini"):
        return "gpt-4.1-mini"

    return raw


def normalize_runtime_bucket(provider: Optional[str], model_name: Optional[str]) -> str:
    """
    Normalise provider/model into a runtime bucket key.

    - Prefer model-based family keys (e.g. "gpt-5.4").
    - Fall back to provider name when the model is missing.
    - Use "unknown" only when both are absent.
    """
    family = _normalize_family_from_model(model_name)
    if family != "unknown":
        return family

    provider_lower = (provider or "").strip().lower()
    if provider_lower:
        return provider_lower

    return "unknown"


def sort_bucket_key(bucket: str) -> Tuple[int, int | str]:
    """
    Provide a stable sort key for bucket labels.

    Buckets in PRIMARY_MODEL_ORDER appear first (in order), followed by other
    buckets alphabetically, with "unknown" last.
    """
    try:
        index = PRIMARY_MODEL_ORDER.index(bucket)
        return (0, index)
    except ValueError:
        pass

    if bucket == "unknown":
        return (2, bucket)

    return (1, bucket)


__all__ = ["PRIMARY_MODEL_ORDER", "normalize_runtime_bucket", "sort_bucket_key"]
