# Repository Guidelines

Use direct, practical language. Push back when assumptions are wrong.

- Build for current behavior only. Do not add legacy compatibility unless explicitly requested.
- The supported local runtime is Docker Compose for infra plus local backend/frontend processes. Keep setup instructions aligned with `README.md`.
- Use the existing reset scripts when they are the fastest safe path:
  - `cd backend && PYTHONPATH=. python scripts/database/recreate_db.py`
  - `cd backend && PYTHONPATH=. python scripts/database/reset_chats.py`
  - `cd backend && PYTHONPATH=. python scripts/database/seed_skills.py`
- Run relevant tests for touched areas. Put tests in the correct backend/frontend test folders.
- For `backend/app`, use structured logging only: `configure_logging(...)`, `log_event(...)`, `bind_log_context(...)`.
- Do not log raw user messages, secrets, file contents, or sensitive tool payloads.
- Keep docs aligned with the shipped open-source runtime. Delete stale internal notes instead of archiving them in the repo.
