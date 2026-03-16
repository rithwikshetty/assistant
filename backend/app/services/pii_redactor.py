"""Utility for redacting text using user's custom redaction list."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Tuple

from ..logging import log_event

logger = logging.getLogger(__name__)

_FILENAME_SEPARATORS_RE = re.compile(r"[_\-.]+")
_WHITESPACE_RE = re.compile(r"\s+")
_INVALID_FILENAME_CHARS_RE = re.compile(r"[^A-Za-z0-9 _-]")
_REDUCTIVE_UNDERSCORE_RE = re.compile(r"_+")
_ALNUM_BOUNDARY_LEFT = r"(?<![A-Za-z0-9])"
_ALNUM_BOUNDARY_RIGHT = r"(?![A-Za-z0-9])"
_NAME_SEPARATOR_PATTERN = r"(?:[\s._-]+)"


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redaction_performed: bool = False
    redaction_hits: List[str] = field(default_factory=list)


class UserRedactionPatterns:
    """Generate regex patterns to catch name variations from user's redaction list."""

    @staticmethod
    def _compile_with_boundaries(pattern_body: str) -> re.Pattern[str]:
        """Compile a case-insensitive pattern wrapped in custom boundaries.

        Treat only alphanumerics as word characters so separators like
        underscores, hyphens, and dots are matched as boundaries.
        """
        return re.compile(
            rf"{_ALNUM_BOUNDARY_LEFT}(?:{pattern_body}){_ALNUM_BOUNDARY_RIGHT}",
            re.IGNORECASE,
        )

    @staticmethod
    def generate_patterns(name: str) -> List[re.Pattern[str]]:
        """Generate all variation patterns for a given name."""
        patterns: List[re.Pattern[str]] = []
        name = name.strip()
        if not name:
            return patterns

        parts = name.split()

        # 1. Full name - case insensitive exact match (with word boundaries)
        escaped = re.escape(name)
        patterns.append(UserRedactionPatterns._compile_with_boundaries(escaped))
        if len(parts) > 1:
            separated_full = _NAME_SEPARATOR_PATTERN.join(re.escape(part) for part in parts)
            patterns.append(UserRedactionPatterns._compile_with_boundaries(separated_full))

        # 2. Reversed order for multi-part names: "Smith, John" or "Smith John"
        if len(parts) > 1:
            leading = re.escape(parts[-1])
            trailing = _NAME_SEPARATOR_PATTERN.join(re.escape(part) for part in parts[:-1])
            reversed_name = rf"{leading}(?:\s*,\s*|{_NAME_SEPARATOR_PATTERN}){trailing}"
            patterns.append(UserRedactionPatterns._compile_with_boundaries(reversed_name))

        # 3. Each part separately (first name, last name) - only for 3+ char parts
        for part in parts:
            if len(part) >= 3:
                patterns.append(UserRedactionPatterns._compile_with_boundaries(re.escape(part)))

        # 4. Initials: "J.S.", "JS", "J S", "J. S." (for multi-part names)
        if len(parts) > 1:
            initials = [p[0].upper() for p in parts if p]
            # J.S. or J. S. (with optional dots and spaces)
            dotted = r"\.?\s*".join(re.escape(i) for i in initials) + r"\.?"
            patterns.append(UserRedactionPatterns._compile_with_boundaries(dotted))
            # JS (consecutive initials)
            if len(initials) >= 2:
                patterns.append(
                    UserRedactionPatterns._compile_with_boundaries(re.escape("".join(initials)))
                )

        # 5. Spaced letters: "J O H N" or "J O H N  S M I T H" (common in OCR artifacts)
        for part in parts:
            if len(part) >= 2:
                spaced = _NAME_SEPARATOR_PATTERN.join(re.escape(c) for c in part.upper())
                patterns.append(UserRedactionPatterns._compile_with_boundaries(spaced))

        return patterns

    @classmethod
    def redact(cls, text: str, entries: List[str]) -> Tuple[str, List[str]]:
        """Apply user's custom redaction list to text."""
        if not text or not entries:
            return text, []

        hits: set[str] = set()
        redacted = text

        for name in entries:
            patterns = cls.generate_patterns(name)
            for pattern in patterns:
                if pattern.search(redacted):
                    def _replacement(match: re.Match[str], n: str = name) -> str:
                        hits.add(n)
                        return "[REDACTED NAME]"
                    redacted = pattern.sub(_replacement, redacted)

        return redacted, sorted(hits)


async def redact_text(
    text: str | None,
    user_redaction_list: List[str] | None = None,
) -> RedactionResult:
    """Redact names/terms from text using user's custom redaction list.

    Args:
        text: The text to redact.
        user_redaction_list: List of names/terms to redact.
    """
    if not text:
        return RedactionResult(text=text or "")

    redacted_text, hits = UserRedactionPatterns.redact(
        text, user_redaction_list or []
    )

    if hits:
        log_event(
            logger,
            "DEBUG",
            "redaction.applied",
            "timing",
            redaction_hits=hits,
        )

    return RedactionResult(
        text=redacted_text,
        redaction_performed=bool(hits),
        redaction_hits=hits,
    )


def redact_filename(
    filename: str | None,
    user_redaction_list: List[str] | None = None,
) -> RedactionResult:
    """Redact sensitive terms from filenames while preserving file extension."""
    raw_name = (filename or "").strip() or "document"
    stem, dot, extension = raw_name.rpartition(".")
    if not dot:
        stem = raw_name
        extension = ""

    normalized_stem = _FILENAME_SEPARATORS_RE.sub(" ", stem or "document")
    normalized_stem = _WHITESPACE_RE.sub(" ", normalized_stem).strip() or "document"

    redacted_stem, hits = UserRedactionPatterns.redact(normalized_stem, user_redaction_list or [])
    if not hits:
        return RedactionResult(text=raw_name, redaction_performed=False, redaction_hits=[])

    safe_stem = redacted_stem.replace("[REDACTED NAME]", "REDACTED_NAME")
    safe_stem = _INVALID_FILENAME_CHARS_RE.sub("_", safe_stem)
    safe_stem = _WHITESPACE_RE.sub("_", safe_stem).strip("._- ")
    safe_stem = _REDUCTIVE_UNDERSCORE_RE.sub("_", safe_stem) or "redacted_file"

    if extension:
        safe_extension = re.sub(r"[^A-Za-z0-9]", "", extension)[:16]
        if safe_extension:
            return RedactionResult(
                text=f"{safe_stem}.{safe_extension}",
                redaction_performed=True,
                redaction_hits=sorted(hits),
            )

    return RedactionResult(
        text=safe_stem,
        redaction_performed=True,
        redaction_hits=sorted(hits),
    )
