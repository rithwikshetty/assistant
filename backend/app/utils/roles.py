from __future__ import annotations

from typing import Iterable

from sqlalchemy import or_


def normalize_role(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized:
            return normalized
    return "user"


def is_admin_role(value: object) -> bool:
    return normalize_role(value) == "admin"


def normalize_role_set(roles: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for role in roles:
        normalized_role = normalize_role(role)
        if normalized_role:
            normalized.add(normalized_role)
    return normalized


def non_admin_role_filter(role_column):
    return or_(role_column.is_(None), role_column != "admin")
