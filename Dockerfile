FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Pre-cache the MCP github server so the first session doesn't pay ~10s npm fetch.
# Non-fatal if the download fails (e.g. offline build) — MCPManager skips broken servers.
RUN npx -y @modelcontextprotocol/server-github --help >/dev/null 2>&1 || true

COPY src/ src/
COPY config/ config/
COPY agents/ agents/
COPY pipelines/ pipelines/
COPY skills/ skills/

RUN mkdir -p uploads projects

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
