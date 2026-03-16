# Technical Architecture

`assistant` is a local-first SPA + API application.

## Services

- frontend: Vite/React UI running locally in development
- backend: FastAPI API and chat runtime running locally in development
- sandbox: isolated Python execution service for code tools
- postgres: primary relational store
- redis: pubsub and transient runtime coordination

## Storage

- relational data and skills: Postgres
- uploaded and generated files: local filesystem storage controlled by `LOCAL_STORAGE_PATH`
- transient runtime/event coordination: Redis

## Runtime Shape

- the app auto-provisions a single local workspace user and does not require login
- chat models are OpenAI-only
- project file retrieval and file reading remain available
- project indexing, staged file processing, and archive generation run in-process in the backend
- public project browsing, project sharing, and project knowledge management are part of the shipped runtime

## Local Development Shape

- Docker Compose runs only infra services: Postgres, Redis, sandbox
- the backend is started with `backend/scripts/run_dev.sh`
- the frontend is started with `npm run dev`
