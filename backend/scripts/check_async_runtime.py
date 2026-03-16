#!/usr/bin/env python3
"""Fail if runtime sync SQLAlchemy patterns exist in backend/app."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "app"

# Allow explicit sync bootstrap helpers in config/database.py only.
ALLOWED_FILES = {
    str(APP_DIR / "config" / "database.py"),
}

PATTERNS = {
    "sync_session_import": re.compile(r"^\s*from\s+sqlalchemy\.orm\s+import\s+.*\bSession\b", re.MULTILINE),
    "session_local_usage": re.compile(r"\bSessionLocal\s*\("),
    "sync_query_api": re.compile(r"\.[Qq]uery\s*\("),
}


def main() -> int:
    violations: list[tuple[str, int, str, str]] = []

    for path in APP_DIR.rglob("*.py"):
        path_str = str(path)
        if path_str in ALLOWED_FILES:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"[check_async_runtime] failed to read {path}: {exc}")
            return 2

        lines = text.splitlines()
        for rule_name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                snippet = lines[line_no - 1].strip() if 1 <= line_no <= len(lines) else ""
                violations.append((path_str, line_no, rule_name, snippet))

    if violations:
        print("[check_async_runtime] Sync DB runtime patterns detected:\n")
        for file_path, line_no, rule_name, snippet in sorted(violations):
            print(f"- {file_path}:{line_no} [{rule_name}] {snippet}")
        print("\nFix these before claiming full async runtime cutover.")
        return 1

    print("[check_async_runtime] OK: no runtime sync DB patterns found in backend/app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
