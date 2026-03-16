# Contributing

## Local Development

The supported setup is:

- `docker compose up -d` for Postgres, Redis, and sandbox
- `cd backend && bash scripts/run_dev.sh` for the API
- `cd frontend && npm install && npm run dev` for the UI

Keep changes aligned with `README.md`. Do not add alternate local runtimes unless they are part of the shipped workflow.

## Before Opening A PR

Run the checks that cover your changes.

Frontend:

```bash
cd frontend
npm test
npm run lint
npm run build
```

Backend:

```bash
cd backend
PYTHONPATH=. pytest -q
```

If a full suite is too expensive, run the smallest focused subset that still proves the change.

## Project Rules

- Keep docs and code in sync.
- Prefer deleting stale internal notes over preserving dead references.
- Do not commit secrets, local env files, or generated local machine state.
- Build for current behavior only. Do not add legacy compatibility unless it is explicitly required.
