# Deployment

The supported local deployment path is:

- Docker Compose for infra only: Postgres, Redis, sandbox
- backend started locally with `backend/scripts/run_dev.sh`
- frontend started locally with `npm run dev`

## Start Infra

```bash
docker compose up -d
```

## Start App Processes

Backend:

```bash
cd backend
bash scripts/run_dev.sh
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Notes

- There is no separate worker service.
- File indexing, staged file processing, and archive generation run in-process inside the backend.
- Postgres, Redis, and sandbox stay in Docker because they are support services, not app processes.
