#!/bin/sh
set -eu

cd /app/backend

export PYTHONPATH=.

python scripts/database/migrate_db.py
python scripts/database/seed_skills.py

exec gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w "${GUNICORN_WORKERS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-600}" \
  --keep-alive 30 \
  --worker-tmp-dir /dev/shm \
  -b "0.0.0.0:${PORT:-8000}"
