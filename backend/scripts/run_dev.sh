#!/bin/bash
set -euo pipefail

echo "Starting assistant backend in development mode..."

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "Please update .env with your actual configuration"
fi

HOST="${UVICORN_HOST:-0.0.0.0}"
RELOAD="${UVICORN_RELOAD:-true}"
# Short timeout avoids Ctrl+C feeling stuck when browser keeps long-lived transport connections open.
GRACEFUL_TIMEOUT="${UVICORN_GRACEFUL_TIMEOUT:-2}"

eval "$(python ../scripts/dev_runtime.py backend-env --format shell)"
PORT="${UVICORN_PORT}"

echo "Uvicorn host=${HOST} port=${PORT} reload=${RELOAD} graceful_timeout=${GRACEFUL_TIMEOUT}s"

echo "Checking WebSocket runtime dependencies..."
python - <<'PY'
import importlib.util
import sys

if importlib.util.find_spec("websockets") or importlib.util.find_spec("wsproto"):
    raise SystemExit(0)

print(
    "Missing WebSocket runtime dependency. Install backend requirements or add 'websockets' to the active Python environment.",
    file=sys.stderr,
)
raise SystemExit(1)
PY

echo "Running database migration..."
PYTHONPATH=. python scripts/database/migrate_db.py

echo "Seeding built-in skills..."
PYTHONPATH=. python scripts/database/seed_skills.py

cmd=(
    python -m uvicorn app.main:app
    --host "${HOST}"
    --port "${PORT}"
    --timeout-graceful-shutdown "${GRACEFUL_TIMEOUT}"
)

if [ "${RELOAD}" = "true" ]; then
    cmd+=(--reload)
fi

# Replace shell process so Ctrl+C signals go straight to uvicorn.
exec "${cmd[@]}"
