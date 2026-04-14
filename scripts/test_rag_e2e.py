"""End-to-end RAG verification for courseware_exam pipeline (checklist 1.2 A).

Walks the full chain:
  project → upload .md → ingest job → knowledge status
    → run courseware_exam pipeline → telemetry timeline
    → assert search_docs was invoked by exam_generator with success=True

Usage (requires compose stack up):
    python scripts/test_rag_e2e.py
    python scripts/test_rag_e2e.py --base http://localhost:8000 --api-key ""
    python scripts/test_rag_e2e.py --keep  # don't delete project after run

Exits 0 on success, non-zero with a red reason on failure.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

# Force UTF-8 stdout on Windows so CJK previews don't crash the script.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


SAMPLE_MD = """# 光合作用课件

## 1. 概念
光合作用是绿色植物利用光能，将二氧化碳和水合成有机物（主要是葡萄糖），
并释放氧气的过程。总反应式：6CO2 + 6H2O → C6H12O6 + 6O2。

## 2. 场所
光合作用发生在叶绿体中。叶绿体由基质和类囊体组成，光反应发生在类囊体薄膜上，
暗反应（卡尔文循环）发生在基质中。

## 3. 两阶段

### 2.1 光反应
- 发生部位：类囊体薄膜
- 条件：需要光
- 产物：ATP、NADPH、O2
- 水的光解：2H2O → 4H+ + 4e- + O2

### 2.2 暗反应（卡尔文循环）
- 发生部位：叶绿体基质
- 条件：不需要光，需要光反应产物
- CO2 固定：CO2 + C5 → 2C3
- C3 还原：C3 + ATP + NADPH → (CH2O) + C5

## 4. 影响因素
光照强度、CO2 浓度、温度、水分供应都会影响光合速率。
在弱光下，光照强度是限制因素；在强光下，CO2 浓度是主要限制因素。

## 5. 意义
光合作用是地球上几乎所有生物能量的最终来源，并维持大气中的氧气含量。
"""


def _fail(msg: str) -> None:
    print(f"\n\033[31mFAIL: {msg}\033[0m")
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("API_BASE", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--keep", action="store_true", help="Don't delete project on success")
    parser.add_argument("--timeout-run", type=int, default=600)
    args = parser.parse_args()

    base = args.base.rstrip("/")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    client = httpx.Client(base_url=base, headers=headers, timeout=60.0)

    # ── 0. Health ──────────────────────────────────────────
    _step(0, "Health check")
    try:
        r = client.get("/health")
        r.raise_for_status()
    except Exception as exc:
        _fail(f"cannot reach {base}/health: {exc}")
    _ok(f"{base}/health → {r.status_code}")

    project_id = None
    try:
        # ── 1. Create project ───────────────────────────────
        _step(1, "Create project")
        r = client.post(
            "/api/projects",
            json={
                "name": f"rag_e2e_{int(time.time())}",
                "description": "temp — RAG 1.2 end-to-end check",
                "pipeline": "courseware_exam",
            },
        )
        if r.status_code != 201:
            _fail(f"POST /api/projects → {r.status_code} {r.text}")
        project_id = r.json()["id"]
        _ok(f"project_id={project_id}")

        # ── 2. Upload sample .md ────────────────────────────
        _step(2, "Upload sample .md")
        tmp = Path("_rag_e2e_sample.md")
        tmp.write_text(SAMPLE_MD, encoding="utf-8")
        try:
            with tmp.open("rb") as fp:
                r = client.post(
                    f"/api/projects/{project_id}/files",
                    files={"file": (tmp.name, fp, "text/markdown")},
                )
        finally:
            tmp.unlink(missing_ok=True)
        if r.status_code != 200:
            _fail(f"upload → {r.status_code} {r.text}")
        file_id = r.json()["id"]
        _ok(f"file_id={file_id}")

        # ── 3. Kick off ingest ──────────────────────────────
        _step(3, "Trigger ingest")
        r = client.post(f"/api/projects/{project_id}/files/{file_id}/ingest")
        if r.status_code != 202:
            _fail(f"ingest → {r.status_code} {r.text}")
        job_id = r.json()["job_id"]
        _ok(f"job_id={job_id}")

        # ── 4. Poll job ─────────────────────────────────────
        _step(4, "Poll ingest job")
        deadline = time.time() + 120
        job = None
        while time.time() < deadline:
            r = client.get(f"/api/jobs/{job_id}")
            if r.status_code != 200:
                _fail(f"GET job → {r.status_code} {r.text}")
            job = r.json()
            if job["status"] in ("done", "failed"):
                break
            time.sleep(1.0)
        if job is None or job["status"] != "done":
            _fail(f"ingest job did not finish clean: {job}")
        _ok(f"job done in ~{int(time.time() - (deadline - 120))}s")

        # ── 5. knowledge/status ────────────────────────────
        _step(5, "Check knowledge status")
        r = client.get(f"/api/projects/{project_id}/knowledge/status")
        r.raise_for_status()
        st = r.json()
        print(f"      {st}")
        if st.get("total_chunks", 0) < 1:
            _fail(f"expected total_chunks ≥ 1, got {st}")
        _ok(f"total_chunks={st['total_chunks']}")

        # ── 6. Trigger pipeline run ────────────────────────
        _step(6, "Trigger courseware_exam run")
        r = client.post(
            f"/api/projects/{project_id}/pipelines/courseware_exam/runs",
            json={"input": {"content": SAMPLE_MD}},
        )
        if r.status_code != 202:
            _fail(f"trigger run → {r.status_code} {r.text}")
        run_id = r.json()["run_id"]
        _ok(f"run_id={run_id}")

        # ── 7. Poll run ────────────────────────────────────
        _step(7, "Poll run until terminal")
        t0 = time.time()
        detail = None
        last_status = None
        while time.time() - t0 < args.timeout_run:
            r = client.get(f"/api/runs/{run_id}")
            if r.status_code != 200:
                _fail(f"GET run → {r.status_code} {r.text}")
            detail = r.json()
            if detail["status"] != last_status:
                print(f"      status={detail['status']} (+{int(time.time() - t0)}s)")
                last_status = detail["status"]
            if detail["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(2.0)
        if detail is None or detail["status"] != "completed":
            err = (detail or {}).get("error") or "(no error)"
            _fail(f"run ended as {detail and detail['status']}: {err}")
        _ok(f"run completed in {int(time.time() - t0)}s")

        # ── 8. Telemetry timeline → tool_call events ───────
        _step(8, "Fetch telemetry timeline")
        r = client.get(f"/api/telemetry/runs/{run_id}/timeline")
        r.raise_for_status()
        events = r.json()
        tool_calls = [e for e in events if e["event_type"] == "tool_call"]
        search_calls = [
            e for e in tool_calls if (e.get("payload") or {}).get("tool_name") == "search_docs"
        ]
        print(f"      total events={len(events)}  tool_calls={len(tool_calls)}  "
              f"search_docs={len(search_calls)}")
        if not search_calls:
            names = sorted({(e['payload'] or {}).get('tool_name') for e in tool_calls})
            _fail(
                "no search_docs tool_call event found. "
                f"tool_names seen: {names}. "
                "Check exam_generator ran and invoked search_docs."
            )
        failed = [e for e in search_calls if not (e["payload"] or {}).get("success")]
        if failed:
            previews = [
                (e["payload"] or {}).get("error_msg") or "(no msg)" for e in failed[:3]
            ]
            _fail(f"{len(failed)} search_docs call(s) failed: {previews}")
        _ok(f"{len(search_calls)} search_docs call(s), all success=True")
        for i, e in enumerate(search_calls[:3], 1):
            p = e["payload"] or {}
            print(f"      [{i}] dur={p.get('duration_ms')}ms  args={p.get('args_preview')}")

        # ── 9. Show final output head ──────────────────────
        _step(9, "Pipeline final_output preview")
        fo = detail.get("final_output", "") or ""
        head = fo[:400].replace("\n", " | ")
        print(f"      len={len(fo)}  head: {head}...")

        print("\n\033[32m============================================")
        print(" PASS — 1.2 A (RAG end-to-end) verified")
        print("============================================\033[0m")

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
