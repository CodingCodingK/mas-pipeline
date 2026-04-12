## 1. Build Infrastructure

- [x] 1.1 Create `.dockerignore` at project root — exclude `node_modules`, `__pycache__`, `.venv`, `uploads`, `web/node_modules`, `web/dist`, `.git`, `*.pyc`, `pg_data`, `.plan`
- [x] 1.2 Create `.env.example` with placeholders for all LLM provider API keys (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, DEEPSEEK_API_KEY, TAVILY_API_KEY) and WEB_PORT

## 2. API Service

- [x] 2.1 Create `Dockerfile` at project root — `python:3.12-slim`, `apt-get install bubblewrap`, `pip install .`, copy source, CMD `uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1`
- [x] 2.2 Verify `docker build -t mas-api .` succeeds

## 3. Web Service

- [x] 3.1 Create `web/nginx.conf` — serve static files on port 80, proxy `/api/` to `http://api:8000/api/`, proxy `/health` to `http://api:8000/health`, SPA fallback `try_files $uri $uri/ /index.html`, SSE support (`proxy_buffering off`, extended `proxy_read_timeout`)
- [x] 3.2 Create `web/Dockerfile` — multi-stage: `node:20-alpine` runs `npm ci && npm run build`, `nginx:alpine` copies dist + nginx.conf
- [x] 3.3 Verify `docker build -t mas-web web/` succeeds

## 4. Docker Compose

- [x] 4.1 Update `docker-compose.yaml` — add `api` service with build context `.`, depends_on postgres/redis (service_healthy), env vars (POSTGRES_HOST=postgres, POSTGRES_PORT=5432, REDIS_HOST=redis, REDIS_PORT=6379), env_file `.env`, bind mounts for agents/pipelines/projects/uploads/config/skills
- [x] 4.2 Update `docker-compose.yaml` — add `web` service with build context `./web`, depends_on api, port mapping `${WEB_PORT:-80}:80`
- [x] 4.3 Verify `docker compose build` succeeds for all services

## 5. Scripts

- [x] 5.1 Create `scripts/start.sh` — `docker compose up --build -d && docker compose logs -f api web`; make executable
- [x] 5.2 Create `scripts/seed.sh` — idempotent insert of sample project via `docker compose exec postgres psql`; make executable

## 6. Validation

- [x] 6.1 `docker compose up` — all 4 services start, api healthcheck passes, web serves SPA at `http://localhost`
- [x] 6.2 Browser test — SPA loads, projects page renders, API calls via `/api/` proxy succeed
- [x] 6.3 Bind mount test — edit a file on host, verify api container sees the change
