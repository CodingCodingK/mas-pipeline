## Context

The project currently runs as 4 loosely-coupled pieces: PG 16 + pgvector and Redis 7 via `docker-compose.yaml`, the Python FastAPI backend via `python src/main.py`, and the React SPA via `npm run dev` in `web/`. A new contributor must install Python 3.12, Node 20, and configure local PG/Redis before anything works. Phase 7.1 wraps everything into a single `docker compose up`.

Existing `docker-compose.yaml` already defines `postgres` and `redis` services with healthchecks and named volumes. `settings.yaml` parameterizes PG/Redis connection strings via env vars with defaults (`POSTGRES_HOST:localhost`, `POSTGRES_PORT:5433`, `REDIS_HOST:localhost`, `REDIS_PORT:6379`). The web client uses `VITE_API_BASE` (defaults to `/api`) and `VITE_API_KEY` (Vite build-time env).

## Goals / Non-Goals

**Goals:**
- `docker compose up` starts all 4 services (postgres, redis, api, web) from a clean clone
- Browser at `http://localhost` renders the SPA and all API calls work
- Host directories (agents, pipelines, projects, uploads, config, skills) are bind-mounted so files are directly editable
- New user workflow: `git clone` → copy `.env.example` → fill LLM keys → `docker compose up`

**Non-Goals:**
- Production-grade deployment (TLS, domain, multi-worker, rate limiting)
- Multi-environment compose files (dev/staging/prod split)
- CI/CD pipeline or image registry publishing
- API key authentication in compose (dev mode: empty api_keys = all pass)

## Decisions

### D1: Web service architecture — Nginx container with multi-stage build

**Choice**: Separate `web` service using multi-stage Dockerfile: `node:20-alpine` builds the SPA, `nginx:alpine` serves `dist/` and reverse-proxies `/api/` to `http://api:8000`.

**Alternatives considered**:
- FastAPI `StaticFiles` mount — avoids a container but couples frontend build into the API image (needs Node in API image or host pre-build step); blurs service boundaries
- Vite dev server container — not a "built" deployment; HMR overhead; doesn't represent what users get

**Rationale**: Nginx is the standard way to serve SPAs. Multi-stage keeps the final image ~25 MB (Nginx Alpine + static files). Clean separation: API image has no Node dependency.

### D2: API Dockerfile — single-stage python:3.12-slim + pip + bwrap

**Choice**: `python:3.12-slim`, `pip install .` (uses pyproject.toml), `apt-get install bubblewrap`. CMD: `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1`.

**Alternatives considered**:
- Multi-stage with `uv` — faster install but adds a non-standard tool; `pip` is sufficient for ~20 deps
- Dev container with bind-mount source — not reproducible for "download and run" use case

**Rationale**: Single-stage is simplest. `--workers 1` because SessionRunner is single-process (in-memory registries). bwrap installed for sandbox support; `fail_if_unavailable: false` means it degrades gracefully if kernel capabilities are missing.

### D3: File persistence — bind mounts from host directories

**Choice**: Bind-mount `./agents`, `./pipelines`, `./projects`, `./uploads`, `./config`, `./skills` into the api container at `/app/<dir>`.

**Alternatives considered**:
- Named Docker volumes — self-contained but opaque; can't `ls` or `git diff` files on host

**Rationale**: This project is a single-machine developer tool. Users edit agent prompts and pipeline YAML on the host. Bind mounts make those edits immediately visible inside the container.

### D4: Environment variable injection for container networking

**Choice**: api service gets `POSTGRES_HOST=postgres`, `POSTGRES_PORT=5432`, `REDIS_HOST=redis`, `REDIS_PORT=6379` via compose `environment:`. These override the defaults in `settings.yaml` (`localhost:5433` / `localhost:6379`).

No code changes needed — `settings.yaml` already uses `${VAR:default}` syntax.

### D5: API key auth — dev mode (disabled)

**Choice**: Do not set `MAS_API_KEYS` in compose. Empty list = all requests pass. Web SPA built without `VITE_API_KEY`.

**Rationale**: API key in client-side JS is not real security. For a local/demo deployment, auth friction provides no value. Auth can be enabled later by adding `MAS_API_KEYS` to `.env`.

### D6: Nginx config — SPA fallback + API proxy

- `location /api/` → `proxy_pass http://api:8000/api/;` (includes WebSocket upgrade headers for SSE)
- `location /health` → `proxy_pass http://api:8000/health;`
- `location /` → `try_files $uri $uri/ /index.html;` (SPA history mode fallback)

### D7: Port mapping

- `web`: host `80:80` — browser access point
- `api`: no host port exposed (only reachable via Nginx proxy within the compose network). Internal port 8000.
- `postgres`: host `5433:5432` (unchanged, for direct psql access during dev)
- `redis`: host `6379:6379` (unchanged)

### D8: Seed script

`scripts/seed.sh` uses `docker compose exec postgres psql` to insert a sample project row. `init_db.sql` already seeds the default user, so seed.sh only adds demo data.

## Risks / Trade-offs

- **[bwrap won't activate in standard containers]** → Mitigation: `fail_if_unavailable: false` degrades to no-sandbox. Docker container itself provides isolation. bwrap installed so it works if user runs api natively on Linux host.
- **[Port 80 conflict on host]** → Mitigation: document in `.env.example` how to change `WEB_PORT`. Use `${WEB_PORT:-80}:80` in compose.
- **[Bind-mount permissions on Linux]** → Mitigation: document `DOCKER_UID`/`DOCKER_GID` env vars; api Dockerfile creates a non-root user. Windows/macOS Docker Desktop handles this automatically.
- **[Large build context without .dockerignore]** → Mitigation: `.dockerignore` excludes `node_modules`, `__pycache__`, `.venv`, `uploads`, `pg_data`, `.git`.
- **[init_db.sql only runs on first PG start]** → Mitigation: document that `docker compose down -v` resets the database.
