#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "No .env file found. Copying from .env.example ..."
    cp .env.example .env
    echo "Please edit .env to add your LLM API keys, then re-run this script."
    exit 1
fi

docker compose up --build -d
echo ""
echo "All services starting. Streaming logs (Ctrl+C to detach)..."
echo "Open http://localhost in your browser."
echo ""
docker compose logs -f api web
