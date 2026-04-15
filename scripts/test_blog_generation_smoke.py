"""Smoke test for the blog_generation pipeline against a live stack + real LLM.

Phase 收尾 4.3.c. Unlike `test_e2e_smoke.py` this script does NOT manage
docker compose and does NOT use a fake LLM — it drives the pipeline end to
end against a running stack using whatever provider is configured.

Walks:
  create project → trigger pipeline run → poll to terminal →
  verify final_post is non-empty → export md → cleanup

Usage:
    python scripts/test_blog_generation_smoke.py
    python scripts/test_blog_generation_smoke.py --base http://localhost:8000
    python scripts/test_blog_generation_smoke.py --keep  # leave project
    python scripts/test_blog_generation_smoke.py --timeout 900

Exits 0 on success, non-zero with a red reason on failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


RED = "\033[31m"
GRN = "\033[32m"
RST = "\033[0m"


def _fail(msg: str) -> None:
    print(f"\n{RED}FAIL: {msg}{RST}")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("API_BASE", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--topic",
        default="The rise of small-model inference on commodity hardware",
    )
    args = parser.parse_args()

    base = args.base.rstrip("/")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    client = httpx.Client(base_url=base, headers=headers, timeout=60.0)

    _step(0, "Health check")
    r = client.get("/health")
    if r.status_code != 200:
        _fail(f"health → {r.status_code}")
    _ok(f"{base}/health → 200")

    project_id = None
    try:
        _step(1, "Create project (pipeline=blog_generation)")
        r = client.post(
            "/api/projects",
            json={
                "name": f"blog_gen_smoke_{int(time.time())}",
                "description": "temp — 收尾 4.3.c blog_generation smoke",
                "pipeline": "blog_generation",
            },
        )
        if r.status_code != 201:
            _fail(f"POST /api/projects → {r.status_code} {r.text}")
        project_id = r.json()["id"]
        _ok(f"project_id={project_id}")

        # Defensive: if the project_id reuses a disk directory with stale
        # per-project agent overrides (e.g. from an earlier smoke test),
        # clear them so the global default agents actually run.
        for role in ("researcher", "writer", "reviewer"):
            client.delete(f"/api/projects/{project_id}/agents/{role}")

        _step(2, "Trigger pipeline run")
        r = client.post(
            f"/api/projects/{project_id}/pipelines/blog_generation/runs",
            json={"input": {"topic": args.topic}},
        )
        if r.status_code != 202:
            _fail(f"trigger run → {r.status_code} {r.text}")
        run_id = r.json()["run_id"]
        _ok(f"run_id={run_id}")

        _step(3, "Poll run until terminal")
        t0 = time.time()
        detail = None
        last_status = None
        while time.time() - t0 < args.timeout:
            r = client.get(f"/api/runs/{run_id}")
            if r.status_code != 200:
                _fail(f"GET run → {r.status_code} {r.text}")
            detail = r.json()
            if detail["status"] != last_status:
                print(f"      status={detail['status']} (+{int(time.time() - t0)}s)")
                last_status = detail["status"]
            if detail["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(3.0)
        if detail is None or detail["status"] != "completed":
            err = (detail or {}).get("error") or "(no error)"
            _fail(f"run ended as {detail and detail['status']}: {err}")
        elapsed = int(time.time() - t0)
        _ok(f"run completed in {elapsed}s")

        _step(4, "Verify node outputs")
        outputs = detail.get("outputs") or {}
        MIN_OUTPUT_CHARS = 200  # guard against stub LLM responses
        for slot in ("research", "draft", "final_post"):
            body = outputs.get(slot) or ""
            if len(body) < MIN_OUTPUT_CHARS:
                _fail(
                    f"outputs[{slot}] too short ({len(body)} chars): {body!r}. "
                    f"Expected ≥{MIN_OUTPUT_CHARS} chars from a real LLM response."
                )
            print(f"      {slot}: {len(body)} chars")
        _ok("research/draft/final_post all non-trivial")

        _step(5, "Export markdown")
        r = client.get(f"/api/runs/{run_id}/export", params={"fmt": "md"})
        if r.status_code != 200:
            _fail(f"export md → {r.status_code}")
        body = r.text
        if len(body) < 100:
            _fail(f"export body suspiciously short: {len(body)} chars")
        _ok(f"export markdown: {len(body)} chars")

        _step(6, "Telemetry sanity check")
        # Telemetry has a 2s batched flush; after workflow_runs.status flips to
        # completed, reviewer's node_end may still be in-flight. Retry briefly.
        required = {"researcher", "writer", "reviewer"}
        events: list = []
        node_ends: set[str] = set()
        for _ in range(10):
            r = client.get(f"/api/telemetry/runs/{run_id}/timeline")
            r.raise_for_status()
            events = r.json()
            node_ends = {
                ((e.get("payload") or {}).get("node_name") or "")
                for e in events
                if e.get("event_type") == "pipeline_event"
                and (e.get("payload") or {}).get("pipeline_event_type") == "node_end"
            }
            if required.issubset(node_ends):
                break
            time.sleep(1.5)
        missing = required - node_ends
        if missing:
            _fail(f"telemetry missing node_end for nodes: {sorted(missing)}; "
                  f"seen={sorted(node_ends)}")
        llm_calls = [e for e in events if e.get("event_type") == "llm_call"]
        if not llm_calls:
            _fail("no llm_call events in telemetry — pipeline ran without LLM?")
        _ok(f"pipeline_event node_end for {sorted(node_ends)}; "
            f"llm_call count={len(llm_calls)}")

        print(f"\n{GRN}============================================")
        print(" PASS — 收尾 4.3.c blog_generation smoke")
        print(f"============================================{RST}")

    finally:
        if project_id is not None and not args.keep:
            try:
                client.delete(f"/api/projects/{project_id}")
                print(f"\n(cleanup) deleted project {project_id}")
            except Exception as exc:
                print(f"\n(cleanup) delete project {project_id} failed: {exc}")
        client.close()


if __name__ == "__main__":
    main()
