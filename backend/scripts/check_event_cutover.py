#!/usr/bin/env python3
"""Fail if core docs/scripts regress to removed pre-run chat references."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

TARGETS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "TECHNICAL_ARCHITECTURE.md",
    BACKEND_ROOT / "scripts" / "database",
    BACKEND_ROOT / "scripts" / "test_scripts",
    REPO_ROOT / "frontend" / "lib" / "api" / "chat.ts",
]

SCAN_SUFFIXES = {".md", ".py", ".ts"}

PATTERNS = {
    "removed_submit_endpoint": re.compile(r"/conversations/submit\b"),
    "removed_messages_endpoint": re.compile(r"/conversations/\{conversation_id\}/messages\b"),
}


def iter_target_files() -> Iterable[Path]:
    for target in TARGETS:
        if not target.exists():
            continue
        if target.is_file():
            yield target
            continue
        for path in target.rglob("*"):
            if path.is_file() and path.suffix in SCAN_SUFFIXES:
                yield path


def find_line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def main() -> int:
    violations: List[Tuple[str, int, str, str]] = []

    for path in iter_target_files():
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"[check_event_cutover] failed to read {path}: {exc}")
            return 2

        lines = text.splitlines()
        for rule_name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line_no = find_line_no(text, match.start())
                snippet = lines[line_no - 1].strip() if 1 <= line_no <= len(lines) else ""
                violations.append((str(path), line_no, rule_name, snippet))

    if violations:
        print("[check_event_cutover] Legacy chat references detected:\n")
        for file_path, line_no, rule_name, snippet in sorted(violations):
            print(f"- {file_path}:{line_no} [{rule_name}] {snippet}")
        print("\nUse run/event/timeline terminology and APIs instead of removed message/submit paths.")
        return 1

    print("[check_event_cutover] OK: no removed chat references in guarded docs/scripts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
