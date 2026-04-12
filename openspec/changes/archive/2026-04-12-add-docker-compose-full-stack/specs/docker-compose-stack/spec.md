## ADDED Requirements

### Requirement: API service Dockerfile
The project SHALL have a `Dockerfile` at the project root that builds the FastAPI backend image. The image SHALL use `python:3.12-slim` as base, install project dependencies via `pip install .`, install `bubblewrap` via apt, and run `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1` as CMD.

#### Scenario: Build api image
- **WHEN** `docker compose build api` is run from the project root
- **THEN** the image builds successfully using `python:3.12-slim`, installs all Python dependencies from `pyproject.toml`, and installs `bubblewrap`

#### Scenario: API container starts
- **WHEN** the api container starts
- **THEN** uvicorn listens on `0.0.0.0:8000` with 1 worker and the `/health` endpoint returns `{"status": "ok"}`

### Requirement: Web service multi-stage Dockerfile
The project SHALL have a `web/Dockerfile` that uses a multi-stage build: stage 1 (`node:20-alpine`) runs `npm ci && npm run build` to produce `dist/`; stage 2 (`nginx:alpine`) copies `dist/` and a custom `nginx.conf` into the Nginx image.

#### Scenario: Build web image
- **WHEN** `docker compose build web` is run from the project root
- **THEN** the image builds successfully: Node stage compiles the React SPA, Nginx stage produces a minimal image containing only static files and nginx config

### Requirement: Nginx configuration
The project SHALL have a `web/nginx.conf` that configures Nginx to:
1. Serve static files from `/usr/share/nginx/html` on port 80
2. Proxy `/api/` requests to `http://api:8000/api/` with appropriate headers (Host, X-Real-IP, X-Forwarded-For, X-Forwarded-Proto)
3. Proxy `/health` requests to `http://api:8000/health`
4. Fall back to `/index.html` for all other paths (SPA history mode via `try_files $uri $uri/ /index.html`)
5. Support SSE by setting `proxy_buffering off` and `proxy_read_timeout` to a suitable value for long-lived connections

#### Scenario: SPA page loads
- **WHEN** a browser requests `http://localhost/` or any SPA route like `/projects/1`
- **THEN** Nginx serves `index.html` and the React app renders

#### Scenario: API proxy
- **WHEN** the SPA makes a request to `/api/health`
- **THEN** Nginx proxies the request to `http://api:8000/api/health` and returns the response

#### Scenario: SSE streaming
- **WHEN** the SPA opens an SSE connection to `/api/runs/{id}/stream` or `/api/notify/stream`
- **THEN** Nginx proxies without buffering and the connection stays open for event streaming

### Requirement: Docker Compose full stack
The `docker-compose.yaml` SHALL define 4 services: `postgres`, `redis`, `api`, `web`. The `api` service SHALL:
1. Build from `./Dockerfile`
2. Depend on `postgres` and `redis` with `condition: service_healthy`
3. Set environment variables: `POSTGRES_HOST=postgres`, `POSTGRES_PORT=5432`, `REDIS_HOST=redis`, `REDIS_PORT=6379`
4. Load LLM provider API keys from the `.env` file via `env_file: .env`
5. Bind-mount host directories: `./agents`, `./pipelines`, `./projects`, `./uploads`, `./config`, `./skills` into the container at `/app/<dir>`
6. NOT expose ports to the host (only reachable via Nginx within compose network)

The `web` service SHALL:
1. Build from `./web/Dockerfile` with context `./web`
2. Depend on `api`
3. Map host port `${WEB_PORT:-80}` to container port 80

#### Scenario: Clean clone full stack startup
- **WHEN** a user runs `git clone`, copies `.env.example` to `.env`, fills in LLM API keys, and runs `docker compose up`
- **THEN** all 4 services start in order (postgres → redis → api → web), the database is initialized via `init_db.sql`, and the browser at `http://localhost` shows the SPA

#### Scenario: Host file edits visible in container
- **WHEN** a user edits `agents/writer.md` on the host machine
- **THEN** the api container sees the updated file immediately without restart

#### Scenario: Container restart preserves data
- **WHEN** `docker compose down` followed by `docker compose up` is run
- **THEN** PG data (named volume), uploaded files, and agent/pipeline configs (bind mounts) are preserved

### Requirement: Docker ignore file
The project SHALL have a `.dockerignore` file that excludes at minimum: `node_modules`, `__pycache__`, `.venv`, `uploads`, `web/node_modules`, `web/dist`, `.git`, `*.pyc`, `pg_data`.

#### Scenario: Build context is small
- **WHEN** `docker compose build` runs
- **THEN** the build context excludes large/irrelevant directories and the build completes efficiently

### Requirement: Environment example file
The project SHALL have a `.env.example` file that documents all environment variables needed by the compose stack. It SHALL include placeholder entries for LLM provider API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY, TAVILY_API_KEY) and the configurable web port (WEB_PORT).

#### Scenario: New user setup
- **WHEN** a new user copies `.env.example` to `.env` and fills in at least one LLM provider key
- **THEN** `docker compose up` starts successfully and the system can route LLM calls to the configured provider

### Requirement: Start script
The project SHALL have a `scripts/start.sh` that wraps `docker compose up` with build and log following. It SHALL be executable and work on Linux/macOS.

#### Scenario: One-command startup
- **WHEN** a user runs `./scripts/start.sh`
- **THEN** Docker Compose builds images (if needed) and starts all services, with logs streaming to the terminal

### Requirement: Seed script
The project SHALL have a `scripts/seed.sh` that inserts sample data (a demo project) into the running PG database via `docker compose exec`. It SHALL be idempotent (re-running does not create duplicates).

#### Scenario: Seed demo data
- **WHEN** a user runs `./scripts/seed.sh` after `docker compose up`
- **THEN** a sample project exists in the `projects` table and the SPA projects page lists it

#### Scenario: Idempotent seed
- **WHEN** `scripts/seed.sh` is run twice
- **THEN** no duplicate projects are created
