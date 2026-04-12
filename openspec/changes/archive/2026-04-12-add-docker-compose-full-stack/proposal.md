## Why

The project has 6 phases of backend + frontend code, but no way to run it as a complete stack without manually starting Python, Node, PG, and Redis on the development machine. A new contributor must install Python 3.12, Node 20, PostgreSQL 16 with pgvector, and Redis 7 before they can even see the app. Phase 7.1 closes this gap: `docker compose up` brings up everything.

## What Changes

- Add `api` service to `docker-compose.yaml` — Python FastAPI backend in a `python:3.12-slim` container with `bwrap` installed for sandbox support
- Add `web` service to `docker-compose.yaml` — multi-stage build (Node 20 → Nginx Alpine) serving the React SPA and reverse-proxying `/api/` to the api service
- Add `Dockerfile` (project root) for the api service
- Add `web/Dockerfile` for the web service (multi-stage: build + serve)
- Add `web/nginx.conf` — SPA history fallback + `/api/` reverse proxy to `http://api:8000`
- Add `.dockerignore` to exclude `node_modules`, `__pycache__`, `.venv`, `uploads`, `pg_data` etc. from build context
- Add `.env.example` — template for LLM provider API keys (the only thing a new user must fill in)
- Add `scripts/start.sh` — one-liner wrapper around `docker compose up`
- Add `scripts/seed.sh` — insert a sample project into PG for first-run demo
- Modify `docker-compose.yaml` — add `api` and `web` services, bind-mount host directories (uploads, projects, agents, pipelines, config, skills), wire `depends_on` with healthcheck conditions
- API key auth runs in dev mode (empty `api_keys` list = all requests pass) — no key configuration in compose

## Capabilities

### New Capabilities
- `docker-compose-stack`: Full-stack Docker Compose orchestration — Dockerfile for api, multi-stage Dockerfile for web (Nginx), nginx config, .dockerignore, .env.example, start/seed scripts, and updated compose file with 4 services (postgres, redis, api, web)

### Modified Capabilities
(none — this is a packaging/deployment layer, no spec-level behavior changes to existing capabilities)

## Impact

- **New files**: `Dockerfile`, `web/Dockerfile`, `web/nginx.conf`, `.dockerignore`, `.env.example`, `scripts/start.sh`, `scripts/seed.sh`
- **Modified files**: `docker-compose.yaml`
- **No backend code changes** — all existing Python/TS source untouched
- **Dependencies**: Docker and Docker Compose required on host (no Python/Node needed)
- **Port allocation**: web on host port 80 (or 3000), api internal on 8000, PG on 5433, Redis on 6379
