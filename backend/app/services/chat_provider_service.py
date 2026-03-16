"""Helpers for resolving chat provider/model settings across runtime and admin APIs."""

from __future__ import annotations

import time
from typing import Any, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ..config.settings import settings
from ..database.models import AppSetting

# ── Provider resolution cache ──────────────────────────────────────────
_provider_cache: Optional[Tuple[str, str, str]] = None
_provider_cache_time: float = 0.0
_PROVIDER_CACHE_TTL: float = 30.0  # seconds

_ALLOWED_PROVIDERS = {"openai"}
_OPENAI_GPT_5_4_MODEL = "gpt-5.4"
_SETTING_KEYS = ("chat_default_model", "chat_power_model")


def _normalize_provider(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if candidate in _ALLOWED_PROVIDERS else None


def _normalize_model(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if lowered.startswith("gpt-5.4"):
        return _OPENAI_GPT_5_4_MODEL
    return None


def provider_for_model(model_name: str) -> str:
    normalized = _normalize_model(model_name)
    if not normalized:
        raise ValueError("Unsupported chat model selection")
    return "openai"


def _provider_has_credentials(provider: str) -> bool:
    if provider == "openai":
        return bool(settings.openai_api_key and settings.openai_api_key.strip())
    return False


def _resolve_from_settings_map(setting_map: dict[str, str]) -> Tuple[str, str, str]:
    default_model = _normalize_model(setting_map.get("chat_default_model"))
    power_model = _normalize_model(setting_map.get("chat_power_model"))

    if default_model is None:
        default_model = _normalize_model(getattr(settings, "chat_default_model", None))

    if default_model is None:
        default_model = _OPENAI_GPT_5_4_MODEL

    if power_model is None:
        power_model = _normalize_model(getattr(settings, "chat_power_model", None))

    if power_model is None:
        power_model = default_model

    provider = provider_for_model(default_model)
    return provider, default_model, power_model


def _resolve_cached_sync(db: Session) -> Tuple[str, str, str]:
    global _provider_cache, _provider_cache_time

    now = time.monotonic()
    if _provider_cache is not None and (now - _provider_cache_time) < _PROVIDER_CACHE_TTL:
        return _provider_cache

    setting_map: dict[str, str] = {}
    try:
        rows = (
            db.query(AppSetting.key, AppSetting.value)
            .filter(AppSetting.key.in_(_SETTING_KEYS))
            .all()
        )
        setting_map = {str(row[0]): str(row[1]) for row in rows if row and row[0] and row[1]}
    except Exception:
        setting_map = {}

    result = _resolve_from_settings_map(setting_map)
    _provider_cache = result
    _provider_cache_time = now
    return result


async def _resolve_cached_async(db: AsyncSession) -> Tuple[str, str, str]:
    global _provider_cache, _provider_cache_time

    now = time.monotonic()
    if _provider_cache is not None and (now - _provider_cache_time) < _PROVIDER_CACHE_TTL:
        return _provider_cache

    setting_map: dict[str, str] = {}
    try:
        rows = await db.execute(
            select(AppSetting.key, AppSetting.value).where(AppSetting.key.in_(_SETTING_KEYS))
        )
        setting_map = {str(row[0]): str(row[1]) for row in rows.all() if row and row[0] and row[1]}
    except Exception:
        setting_map = {}

    result = _resolve_from_settings_map(setting_map)
    _provider_cache = result
    _provider_cache_time = now
    return result


def _resolve_effective_model_for_user(
    *,
    user: Optional[Any],
    default_model: str,
    power_model: str,
) -> str:
    override_model = _normalize_model(getattr(user, "model_override", None))
    if override_model is not None:
        return override_model

    user_tier = str(getattr(user, "user_tier", "default") or "default").strip().lower()
    return power_model if user_tier == "power" else default_model


def resolve_chat_provider(db: Session) -> Tuple[str, str, str]:
    """Return configured provider + default/power models for admin/runtime use."""
    return _resolve_cached_sync(db)


async def resolve_chat_provider_async(db: AsyncSession) -> Tuple[str, str, str]:
    """Async variant of configured provider + default/power model resolution."""
    return await _resolve_cached_async(db)


def resolve_chat_provider_for_user(
    db: Session,
    user: Optional[Any],
) -> Tuple[str, str]:
    """Resolve the effective provider and model for a specific user."""
    _, default_model, power_model = resolve_chat_provider(db)
    effective_model = _resolve_effective_model_for_user(
        user=user,
        default_model=default_model,
        power_model=power_model,
    )
    provider = provider_for_model(effective_model)
    ensure_provider_is_configured(provider)
    return provider, effective_model


async def resolve_chat_provider_for_user_async(
    db: AsyncSession,
    user: Optional[Any],
) -> Tuple[str, str]:
    """Async variant of effective provider/model resolution for a specific user."""
    _, default_model, power_model = await resolve_chat_provider_async(db)
    effective_model = _resolve_effective_model_for_user(
        user=user,
        default_model=default_model,
        power_model=power_model,
    )
    provider = provider_for_model(effective_model)
    ensure_provider_is_configured(provider)
    return provider, effective_model


def invalidate_provider_cache() -> None:
    """Clear the cached provider resolution."""
    global _provider_cache, _provider_cache_time
    _provider_cache = None
    _provider_cache_time = 0.0


def ensure_provider_is_configured(provider: str) -> None:
    """Raise ValueError when credentials for the chosen provider are missing."""
    normalized = _normalize_provider(provider)
    if not normalized:
        raise ValueError("Invalid provider")

    if not _provider_has_credentials(normalized):
        if normalized == "openai":
            raise ValueError("OPENAI_API_KEY is not configured on the server")
        raise ValueError("Chat provider is not correctly configured on the server")


def chat_model_options() -> Tuple[str, ...]:
    """Return selectable chat model identifiers for admin UI."""
    return (_OPENAI_GPT_5_4_MODEL,)


def validate_chat_model(value: str) -> str:
    """Validate and normalize a chat model selection."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Model name is required")
    normalized = _normalize_model(value)
    if normalized:
        return normalized
    raise ValueError("Unsupported chat model selection")


__all__ = [
    "resolve_chat_provider",
    "resolve_chat_provider_async",
    "resolve_chat_provider_for_user",
    "resolve_chat_provider_for_user_async",
    "provider_for_model",
    "invalidate_provider_cache",
    "ensure_provider_is_configured",
    "chat_model_options",
    "validate_chat_model",
]
