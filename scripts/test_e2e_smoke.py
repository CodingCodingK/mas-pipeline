"""End-to-end smoke test against the live docker-compose stack.

Runs the full blog_with_review pipeline via REST, exercising all three
interrupt branches (approve / reject & redo / edit), plus a RAG ingest
branch (upload -> ingest job -> SSE/poll to done -> verify chunks landed
in pgvector), with an embedded fake LLM on localhost:9999 so no real
provider is contacted. The fake serves both /v1/chat/completions and
/v1/embeddings, the latter returning 768-dim deterministic vectors.

Usage:
    python scripts/test_e2e_smoke.py

Prerequisites:
    - Docker Desktop running
    - Ports 80, 5433, 6379, 8000, 9999 free on the host
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from typing import Iterator

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

# ── Constants ───────────────────────────────────────────────

FAKE_LLM_PORT = 9999
API_BASE = "http://localhost"  # via nginx (web service), which proxies /api/ + /health to api:8000
COMPOSE_FILES = ["-f", "docker-compose.yaml", "-f", "docker-compose.smoke.yaml"]
HEALTH_TIMEOUT = 90
STREAM_TIMEOUT = 180

MARKER = "MAS_SMOKE_DETERMINISTIC_OUTPUT"
EDITED_MARKER = "EDITED_SMOKE_CONTENT"
FAKE_COMPLETION_TEXT = (
    "# Smoke Test Blog Post\n\n"
    f"This is a deterministic response from the fake LLM. Marker: {MARKER}.\n\n"
    "## Section One\n\nFixed body content for the smoke test.\n"
)

# ── Fake LLM server ─────────────────────────────────────────


def _build_fake_app() -> FastAPI:
    app = FastAPI()

    def _nonstream_body(model: str) -> dict:
        return {
            "id": "chatcmpl-smoke",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": FAKE_COMPLETION_TEXT,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 60,
            },
        }

    def _stream_chunks(model: str) -> Iterator[bytes]:
        # Initial role chunk
        first = {
            "id": "chatcmpl-smoke",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [
                {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
            ],
        }
        yield f"data: {json.dumps(first)}\n\n".encode()

        # One content chunk with the full fake text (simpler & deterministic)
        content_chunk = {
            "id": "chatcmpl-smoke",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": FAKE_COMPLETION_TEXT},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(content_chunk)}\n\n".encode()

        # Final chunk with finish_reason + usage
        final = {
            "id": "chatcmpl-smoke",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 50,
                "total_tokens": 60,
            },
        }
        yield f"data: {json.dumps(final)}\n\n".encode()
        yield b"data: [DONE]\n\n"

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = await request.json()
        model = payload.get("model", "gpt-smoke")
        msgs = payload.get("messages", [])
        print(
            f"[fake-llm] POST /v1/chat/completions stream={payload.get('stream')} "
            f"model={model} msgs={len(msgs)} first_role={msgs[0].get('role') if msgs else None}"
        )
        if payload.get("stream"):
            return StreamingResponse(
                _stream_chunks(model), media_type="text/event-stream"
            )
        return JSONResponse(_nonstream_body(model))

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        payload = await request.json()
        inputs = payload.get("input", [])
        if isinstance(inputs, str):
            inputs = [inputs]
        n = max(len(inputs), 1)
        # Deterministic non-zero vectors so pgvector cosine ops don't NaN if a
        # downstream caller actually queries the index. Each chunk gets a
        # slightly different first dim to avoid all-identical rows.
        vecs = []
        for i in range(n):
            v = [0.0] * 768
            v[0] = 0.1 + (i * 0.001)
            vecs.append({"object": "embedding", "index": i, "embedding": v})
        return JSONResponse(
            {
                "object": "list",
                "data": vecs,
                "model": "nomic-embed-text",
                "usage": {"prompt_tokens": n, "total_tokens": n},
            }
        )

    return app


class _UvicornThread(threading.Thread):
    def __init__(self, app: FastAPI, port: int) -> None:
        super().__init__(daemon=True)
        # Bind 0.0.0.0 so the api container can reach the fake via
        # host.docker.internal. Binding 127.0.0.1 would be host-loopback only
        # and unreachable from inside Docker's bridge network.
        config = uvicorn.Config(
            app, host="0.0.0.0", port=port, log_level="warning", access_log=False
        )
        self.server = uvicorn.Server(config)

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


@contextmanager
def fake_llm_server() -> Iterator[None]:
    if not _port_free(FAKE_LLM_PORT):
        raise RuntimeError(
            f"Port {FAKE_LLM_PORT} is already in use — free it before running the smoke test"
        )
    thread = _UvicornThread(_build_fake_app(), FAKE_LLM_PORT)
    thread.start()
    # Wait until the fake actually serves a request
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=1.0) as c:
                r = c.post(
                    f"http://127.0.0.1:{FAKE_LLM_PORT}/v1/chat/completions",
                    json={"model": "x", "messages": [], "stream": False},
                )
                if r.status_code == 200:
                    break
        except Exception:
            time.sleep(0.2)
    else:
        thread.stop()
        raise RuntimeError("Fake LLM failed to start within 10s")
    try:
        yield
    finally:
        thread.stop()
        thread.join(timeout=5)


# ── Compose lifecycle ───────────────────────────────────────


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def compose_up() -> None:
    print("[compose] building + starting stack...")
    _run(["docker", "compose", *COMPOSE_FILES, "up", "-d", "--build"])

    deadline = time.time() + HEALTH_TIMEOUT
    last_err = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API_BASE}/health", timeout=2.0)
            if r.status_code == 200:
                print(f"[compose] api healthy ({int(time.time() - (deadline - HEALTH_TIMEOUT))}s)")
                return
            last_err = f"status {r.status_code}"
        except Exception as e:
            last_err = str(e)
        time.sleep(2)
    raise RuntimeError(f"API did not become healthy within {HEALTH_TIMEOUT}s: {last_err}")


def compose_logs_tail() -> None:
    try:
        res = _run(
            ["docker", "compose", *COMPOSE_FILES, "logs", "api", "--tail", "100"],
            check=False,
        )
        sys.stderr.write("\n[compose] api logs (tail 100):\n")
        sys.stderr.write(res.stdout or "")
        sys.stderr.write(res.stderr or "")
        sys.stderr.write("\n")
    except Exception as e:
        sys.stderr.write(f"[compose] failed to dump logs: {e}\n")


def compose_down() -> None:
    print("[compose] tearing down stack...")
    try:
        _run(["docker", "compose", *COMPOSE_FILES, "down"], check=False)
    except Exception as e:
        sys.stderr.write(f"[compose] down failed: {e}\n")


# ── REST helpers ────────────────────────────────────────────


def create_project(client: httpx.Client, name: str) -> int:
    r = client.post(
        "/api/projects",
        json={
            "name": name,
            "description": "smoke",
            "pipeline": "blog_with_review",
        },
    )
    assert r.status_code == 201, f"create project: {r.status_code} {r.text}"
    return r.json()["id"]


_SMOKE_AGENT_TEMPLATE = (
    "---\n"
    "description: smoke {role} override (no tools, single turn)\n"
    "model_tier: medium\n"
    "tools: []\n"
    "max_turns: 2\n"
    "---\n"
    "You are a smoke test {role}. Reply with the fixed test response.\n"
)


def put_agent_override(client: httpx.Client, project_id: int) -> None:
    """Install minimal no-tool overrides for every agent the blog_with_review
    pipeline uses. This keeps the run entirely LLM-call bound so the fake LLM
    can return deterministic text and the pipeline completes in seconds."""
    for role in ("researcher", "writer", "reviewer"):
        content = _SMOKE_AGENT_TEMPLATE.format(role=role)
        r = client.put(
            f"/api/projects/{project_id}/agents/{role}",
            json={"content": content},
        )
        assert r.status_code in (200, 201), f"put agent {role}: {r.status_code} {r.text}"


def _parse_sse_lines(resp: httpx.Response) -> Iterator[tuple[str, dict]]:
    """Yield (event_name, payload_dict) tuples from an SSE response."""
    current_event = "message"
    for raw in resp.iter_lines():
        if raw is None:
            continue
        if raw == "":
            current_event = "message"
            continue
        if raw.startswith(":"):
            continue
        if raw.startswith("event:"):
            current_event = raw[len("event:"):].strip()
            continue
        if raw.startswith("data:"):
            data_str = raw[len("data:"):].strip()
            try:
                payload = json.loads(data_str) if data_str else {}
            except json.JSONDecodeError:
                payload = {"raw": data_str}
            yield current_event, payload


def trigger_stream(client: httpx.Client, project_id: int) -> str:
    """Kick off a streaming run, capture run_id from the `started` event, close.

    We only need the SSE connection long enough to read the `started` event.
    After that, polling `/api/runs/{id}` is the robust way to observe pause
    and terminal state transitions (status-only SSE stream doesn't reliably
    surface `pipeline_pause`).
    """
    with client.stream(
        "POST",
        f"/api/projects/{project_id}/pipelines/blog_with_review/runs",
        params={"stream": "true"},
        json={"input": {"topic": "smoke test"}},
        timeout=STREAM_TIMEOUT,
    ) as resp:
        assert resp.status_code == 200, f"trigger stream: {resp.status_code}"
        for name, payload in _parse_sse_lines(resp):
            if name == "started":
                run_id = payload.get("run_id")
                assert run_id, "started event had no run_id"
                return run_id
    raise AssertionError("stream closed before started event arrived")


def wait_for_paused(client: httpx.Client, run_id: str, timeout: float = 120) -> None:
    """Poll run detail until status == paused. SSE events don't surface
    pipeline_pause reliably in the status-only stream (documented caveat),
    so polling is the robust path."""
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200, f"get run: {r.status_code} {r.text}"
        detail = r.json()
        status = detail["status"]
        if status != last_status:
            print(f"  [poll {run_id}] status={status}")
            last_status = status
        if status == "paused":
            return
        if status in ("failed", "cancelled", "completed"):
            raise AssertionError(
                f"run {run_id} ended unexpectedly in status={status} before pause; "
                f"error={detail.get('error')}"
            )
        time.sleep(1)
    raise AssertionError(f"run {run_id} did not pause within {timeout}s (last status={last_status})")


def wait_for_status(
    client: httpx.Client, run_id: str, target: str, timeout: float = 180
) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200, f"get run: {r.status_code} {r.text}"
        last = r.json()
        if last["status"] == target:
            return last
        if last["status"] in ("failed", "cancelled"):
            raise AssertionError(
                f"run {run_id} reached terminal status={last['status']}: {last.get('error')}"
            )
        time.sleep(1)
    raise AssertionError(
        f"run {run_id} did not reach {target} within {timeout}s (last={last.get('status')})"
    )


def resume(client: httpx.Client, run_id: str, value: dict) -> None:
    r = client.post(f"/api/runs/{run_id}/resume", json={"value": value})
    assert r.status_code == 202, f"resume: {r.status_code} {r.text}"


def upload_md_file(client: httpx.Client, project_id: int, name: str, body: str) -> int:
    files = {"file": (name, body.encode("utf-8"), "text/markdown")}
    r = client.post(f"/api/projects/{project_id}/files", files=files)
    assert r.status_code == 200, f"upload file: {r.status_code} {r.text}"
    return r.json()["id"]


def trigger_ingest(client: httpx.Client, project_id: int, file_id: int) -> str:
    r = client.post(f"/api/projects/{project_id}/files/{file_id}/ingest")
    assert r.status_code == 202, f"trigger ingest: {r.status_code} {r.text}"
    return r.json()["job_id"]


def wait_for_job(client: httpx.Client, job_id: str, timeout: float = 60) -> dict:
    """Poll /api/jobs/{id} until terminal. Returns the final job payload."""
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, f"get job: {r.status_code} {r.text}"
        payload = r.json()
        status = payload["status"]
        if status != last_status:
            print(f"  [job {job_id[:8]}] status={status}")
            last_status = status
        if status in ("done", "failed"):
            return payload
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s (last={last_status})")


def export_md(client: httpx.Client, run_id: str) -> str:
    r = client.get(f"/api/runs/{run_id}/export", params={"fmt": "md"})
    assert r.status_code == 200, f"export: {r.status_code} {r.text}"
    return r.text


# ── Branches ────────────────────────────────────────────────


def run_approve_branch(client: httpx.Client, project_id: int) -> None:
    print("[approve] triggering run...")
    run_id = trigger_stream(client, project_id)
    wait_for_paused(client, run_id)
    print(f"[approve] run {run_id} paused; resuming with approve")
    resume(client, run_id, {"action": "approve"})
    detail = wait_for_status(client, run_id, "completed")
    assert detail["final_output"], "final_output empty after approve"
    body = export_md(client, run_id)
    assert MARKER in body, f"approve export missing marker; body={body[:200]}"
    print(f"[approve] OK ({run_id})")


def run_reject_branch(client: httpx.Client, project_id: int) -> None:
    print("[reject] triggering run...")
    run_id = trigger_stream(client, project_id)
    wait_for_paused(client, run_id)
    print(f"[reject] run {run_id} first pause; resuming with reject")
    resume(client, run_id, {"action": "reject", "feedback": "please rewrite"})
    # Let the run leave `paused` (writer_run re-executes) before we poll
    # for the second pause — otherwise we'd match the stale state.
    time.sleep(3)
    wait_for_paused(client, run_id)
    print(f"[reject] run {run_id} second pause; approving")
    resume(client, run_id, {"action": "approve"})
    detail = wait_for_status(client, run_id, "completed")
    assert detail["final_output"], "final_output empty after reject+approve"
    body = export_md(client, run_id)
    assert body.strip(), "reject export empty"
    print(f"[reject] OK ({run_id})")


def run_rag_ingest_branch(client: httpx.Client, project_id: int) -> None:
    """Upload a tiny markdown doc, trigger ingest, verify chunks land in pgvector
    via the chunks REST endpoint and the project knowledge status counts.

    The fake LLM /v1/embeddings returns 768-dim deterministic vectors so the
    full embedder code path (HTTP call, dim check, batch validation, pgvector
    write) is exercised end-to-end without a real embedding service.
    """
    print("[rag] uploading smoke doc...")
    body = (
        "# Smoke RAG Document\n\n"
        "This is a tiny markdown file used by the e2e smoke test to exercise "
        "the RAG ingest pipeline end-to-end.\n\n"
        "## Section\n\n"
        "Embeddings come from the fake LLM. Vector storage is real pgvector. "
        "The point of this branch is to verify the wiring: upload -> parse -> "
        "chunk -> embed -> store -> queryable via REST.\n"
    )
    file_id = upload_md_file(client, project_id, "smoke_rag.md", body)
    print(f"[rag] uploaded file_id={file_id}")

    job_id = trigger_ingest(client, project_id, file_id)
    print(f"[rag] ingest job {job_id[:8]} started")

    payload = wait_for_job(client, job_id)
    assert payload["status"] == "done", (
        f"ingest job ended in status={payload['status']}, error={payload.get('error')}"
    )
    last_event = payload.get("last_event") or {}
    chunks_in_event = last_event.get("chunks", 0)
    assert chunks_in_event > 0, f"ingest done event reports zero chunks: {last_event}"
    print(f"[rag] job done with {chunks_in_event} chunks")

    # Sanity-check the chunks landed in pgvector via the chunks endpoint.
    r = client.get(f"/api/projects/{project_id}/files/{file_id}/chunks")
    assert r.status_code == 200, f"list chunks: {r.status_code} {r.text}"
    page = r.json()
    assert page["total"] == chunks_in_event, (
        f"chunks REST total ({page['total']}) != ingest event chunks ({chunks_in_event})"
    )
    assert page["items"], "chunks REST returned empty items list"
    assert any("smoke" in (c["content"] or "").lower() for c in page["items"]), (
        f"no chunk contains the marker text; first chunk: {page['items'][0]['content'][:120]}"
    )

    # Knowledge status aggregate should reflect the new file.
    r = client.get(f"/api/projects/{project_id}/knowledge/status")
    assert r.status_code == 200, f"knowledge status: {r.status_code} {r.text}"
    status_payload = r.json()
    assert status_payload["file_count"] >= 1, status_payload
    assert status_payload.get("total_chunks", 0) >= chunks_in_event, status_payload
    print(f"[rag] OK (file_id={file_id}, chunks={chunks_in_event})")


def run_edit_branch(client: httpx.Client, project_id: int) -> None:
    print("[edit] triggering run...")
    run_id = trigger_stream(client, project_id)
    wait_for_paused(client, run_id)
    print(f"[edit] run {run_id} paused; resuming with edit")
    resume(client, run_id, {"action": "edit", "edited": EDITED_MARKER})
    detail = wait_for_status(client, run_id, "completed")
    assert detail["final_output"], "final_output empty after edit"
    # Edit replaces writer's output slot (`draft`), but the terminal node is
    # `reviewer` which writes its own output on top. So the edited content
    # lives in outputs["draft"], not in final_output. Use include_all=true to
    # get all node outputs in the export.
    r = client.get(
        f"/api/runs/{run_id}/export",
        params={"fmt": "md", "include_all": "true"},
    )
    assert r.status_code == 200, f"export include_all: {r.status_code}"
    body = r.text
    assert EDITED_MARKER in body, (
        f"edit export missing marker; outputs={list(detail.get('outputs', {}).keys())}"
    )
    print(f"[edit] OK ({run_id})")


# ── Main ────────────────────────────────────────────────────


def main() -> int:
    started = time.time()
    try:
        with fake_llm_server():
            compose_up()
            with httpx.Client(base_url=API_BASE, timeout=30.0) as client:
                project_id = create_project(client, f"smoke-{int(time.time())}")
                put_agent_override(client, project_id)
                print(f"[setup] project_id={project_id} agent override installed")

                run_approve_branch(client, project_id)
                run_reject_branch(client, project_id)
                run_edit_branch(client, project_id)
                run_rag_ingest_branch(client, project_id)
    except AssertionError as e:
        sys.stderr.write(f"\nSMOKE FAIL: {e}\n")
        compose_logs_tail()
        return 1
    except Exception as e:
        sys.stderr.write(f"\nSMOKE ERROR: {e}\n")
        compose_logs_tail()
        return 1
    finally:
        compose_down()

    elapsed = int(time.time() - started)
    print(f"\nSMOKE OK: approve + reject + edit + rag_ingest ({elapsed}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
