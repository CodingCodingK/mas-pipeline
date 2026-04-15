@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist ".env" (
    echo [!] .env not found. Copying from .env.example ...
    copy ".env.example" ".env" >nul
    echo [!] Please edit .env to add your LLM API keys, then re-run this script.
    pause
    exit /b 1
)

echo ============================================================
echo   mas-pipeline : docker compose up --build -d
echo ============================================================
docker compose up --build -d
if errorlevel 1 (
    echo.
    echo [X] docker compose failed. See output above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Service status
echo ============================================================
docker compose ps

echo.
echo ============================================================
echo   Frontend URLs  (open in browser)
echo ============================================================
echo.
echo   Web UI root           http://localhost/
echo   Login page            http://localhost/           (first visit)
echo   Projects list         http://localhost/#/
echo   Pipeline editor       http://localhost/#/pipelines
echo   Project detail        http://localhost/#/projects/{id}
echo   Project - agents tab  http://localhost/#/projects/{id}?tab=agents
echo   Project - pipelines   http://localhost/#/projects/{id}?tab=pipelines
echo   Project - runs tab    http://localhost/#/projects/{id}?tab=runs
echo   Project - files tab   http://localhost/#/projects/{id}?tab=files
echo   Project - dashboard   http://localhost/#/projects/{id}?tab=dashboard
echo   Run detail            http://localhost/#/projects/{id}/runs/{runId}
echo   Chat (new session)    http://localhost/#/projects/{id}/chat
echo   Chat (existing)       http://localhost/#/projects/{id}/chat/{sessionId}
echo.
echo ============================================================
echo   Backend endpoints
echo ============================================================
echo.
echo   API base              http://localhost:8000
echo   Health check          http://localhost:8000/health
echo   OpenAPI docs          http://localhost:8000/docs
echo   ReDoc                 http://localhost:8000/redoc
echo   Postgres (pgvector)   localhost:5433    user=mas  db=mas_pipeline
echo   Redis                 localhost:6379
echo.
echo ============================================================
echo   Claw Gateway (Discord / QQ / WeChat bus)
echo ============================================================
echo.
echo   Container name        mas-gateway
echo   Enable/disable        config/settings.local.yaml : channels.*.enabled
echo   Tail logs             docker compose logs -f gateway
echo   Bot token (Discord)   config/settings.local.yaml : channels.discord.token
echo.
echo ============================================================
echo   Useful commands
echo ============================================================
echo   docker compose logs -f api web
echo   docker compose logs -f gateway
echo   docker compose ps
echo   stop.bat    ^(stops all services^)
echo.
echo Window will stay open. Close it manually when done.
echo.
pause
endlocal
