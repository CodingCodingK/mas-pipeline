@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

echo ============================================================
echo   mas-pipeline : docker compose down (all profiles)
echo ============================================================
docker compose --profile monitoring down
if errorlevel 1 (
    echo.
    echo [X] docker compose down failed. See output above.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Remaining containers (should be empty for this project)
echo ============================================================
docker compose ps

echo.
echo [OK] All mas-pipeline services stopped.
echo      Data volumes (pg_data, redis_data) are preserved.
echo      To also remove volumes:  docker compose down -v
echo.
pause
endlocal
