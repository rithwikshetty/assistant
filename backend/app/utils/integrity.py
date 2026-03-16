"""Shared helpers for interpreting SQLAlchemy IntegrityError."""

from typing import Optional, Set

from sqlalchemy.exc import IntegrityError


def extract_constraint_name(exc: IntegrityError, known_names: Set[str]) -> Optional[str]:
    """Extract the violated constraint name from an IntegrityError.

    Tries ``exc.orig.diag.constraint_name`` first (Postgres driver),
    then falls back to searching the error message for any of *known_names*.
    Returns None when the constraint cannot be identified.
    """
    orig = getattr(exc, "orig", None)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None)
    if isinstance(constraint_name, str) and constraint_name.strip():
        return constraint_name.strip()
    message = str(orig or exc)
    for known in known_names:
        if known in message:
            return known
    return None


def is_constraint_violation(exc: IntegrityError, known_names: Set[str]) -> bool:
    """Check whether the IntegrityError matches any of the given constraint names."""
    name = extract_constraint_name(exc, known_names)
    return name is not None and name in known_names
