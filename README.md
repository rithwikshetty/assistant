# assistant

`assistant` is a local AI workspace built around OpenAI, FastAPI, React, PostgreSQL, Redis, and a sandboxed code runner.

The supported local setup is:

- frontend running locally with Vite
- backend running locally with `backend/scripts/run_dev.sh`
- Docker only for sandbox, Postgres, and Redis

## Features

- chat with OpenAI models
- upload files and search project knowledge
- run code in an isolated sandbox
- manage tasks
- create and store custom skills

## Architecture

- frontend: React/Vite app on the first free local port starting at `3000`
- backend: FastAPI API and chat runtime on the first free local port starting at `8000`
- backend runtime also processes file indexing, staged file processing, and archive generation in-process
- sandbox: isolated Python execution service published on a Docker-assigned free loopback port
- postgres: primary database published on a Docker-assigned free loopback port
- redis: runtime coordination published on a Docker-assigned free loopback port

## Prerequisites

- Docker
- Docker Compose
- Python 3.12
- Node.js 22
- an OpenAI API key

## Quick Start

1. Start the local infra:

```bash
docker compose up -d
```

2. Create backend env:

```bash
cp backend/.env.example backend/.env
```

3. Set at least in `backend/.env`:

```bash
OPENAI_API_KEY=your_key_here
SECRET_KEY=replace-with-a-long-random-secret-at-least-32-characters
```

4. Create frontend env:

```bash
cp frontend/.env.local.example frontend/.env.local
```

5. Start the backend:

```bash
cd backend
bash scripts/run_dev.sh
```

6. In another terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

7. Open the frontend URL printed by `npm run dev`.

The app auto-provisions a single local workspace user. There is no login flow.
The local dev scripts reserve matching frontend/backend ports automatically, and the backend discovers the Docker-published Postgres, Redis, and sandbox ports automatically. You do not need to keep `3000`, `8000`, `5432`, `6379`, or `8100` free.

## Docker Commands

Start infra:

```bash
docker compose up -d
```

Stop infra:

```bash
docker compose down
```

Stop infra and remove volumes:

```bash
docker compose down -v
```

Follow infra logs:

```bash
docker compose logs -f
```

Follow one infra service:

```bash
docker compose logs -f postgres
```

## Environment Variables

Backend required:

- `OPENAI_API_KEY`
- `SECRET_KEY`

Backend optional:

- `LOCAL_USER_EMAIL`
- `LOCAL_USER_NAME`
- `LOCAL_USER_DEPARTMENT`
- `DATABASE_URL`
- `REDIS_URL`
- `SANDBOX_URL`
- `FRONTEND_URL`
- `API_BASE_URL`

Frontend optional:

- `VITE_ENABLE_PROJECTS`

## Data Persistence

Docker volumes are used for persistent infra data:

- `pgdata`: Postgres data
- `redisdata`: Redis data

Built-in and custom skills are persisted in Postgres. File bytes and generated files are stored locally according to `LOCAL_STORAGE_PATH` in `backend/.env`.

## Resetting Local State

Recreate the database:

```bash
cd backend
PYTHONPATH=. python scripts/database/recreate_db.py
```

Reset chats only:

```bash
cd backend
PYTHONPATH=. python scripts/database/reset_chats.py
```

Seed built-in skills only:

```bash
cd backend
PYTHONPATH=. python scripts/database/seed_skills.py
```

## Troubleshooting

If the app does not come up cleanly:

- verify Docker infra is up with `docker compose ps`
- verify `OPENAI_API_KEY` is set in `backend/.env`
- run the backend from `backend/scripts/run_dev.sh`
- run the frontend with `npm run dev`
- inspect infra logs with `docker compose logs -f`
- if startup state is broken, reset infra with `docker compose down -v` and restart it

## Verification

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

## Repository Docs

- [Technical Architecture](./TECHNICAL_ARCHITECTURE.md)
- [Deployment Notes](./DEPLOYMENT.md)
- [Authentication and Session Model](./documentation/authentication.md)
- [Contributing](./CONTRIBUTING.md)
- [Code of Conduct](./CODE_OF_CONDUCT.md)
- [Security](./SECURITY.md)
- [License](./LICENSE)
