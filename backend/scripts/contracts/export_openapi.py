from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://assistant:assistant@localhost/assistant")
os.environ.setdefault("SECRET_KEY", "assistant-openapi-export-secret-key-1234")

from app.main import app


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: PYTHONPATH=. python scripts/contracts/export_openapi.py <output-path>")
        return 1

    output_path = Path(sys.argv[1]).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
