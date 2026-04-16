"""Layer 2: Empty-input fast-fail test for courseware_exam pipeline.

Verifies the "铁律" (iron rule) chain: when a project has NO RAG documents,
the pipeline should gracefully produce an empty report instead of
hallucinating a fake exam.

Chain under test:
  parser  → "状态：无可用课件"
  analyzer → "状态：无可用课件"
  exam_generator → "状态：无法生成"
  exam_reviewer  → "无法生成：未找到匹配的课件内容"

Usage (requires compose stack up):
    python scripts/test_courseware_empty_input.py
    python scripts/test_courseware_empty_input.py --base http://localhost:8000
    python scripts/test_courseware_empty_input.py --keep   # don't delete project
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

passed = 0
failed_count = 0


def _fail(msg: str) -> None:
    print(f"\n\033[31mFAIL: {msg}\033[0m")
    sys.exit(1)


def _ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  [OK] {msg}")


def _check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed_count
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed_count += 1
        print(f"  [FAIL] {name} — {detail}")


def _step(n: int, msg: str) -> None:
    print(f"\n[{n}] {msg}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("API_BASE", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--keep", action="store_true", help="Don't delete project on success")
    parser.add_argument("--timeout-run", type=int, default=300)
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
        # ── 1. Create EMPTY project (no files, no RAG) ─────
        _step(1, "Create empty project (no files uploaded)")
        r = client.post(
            "/api/projects",
            json={
                "name": f"empty_input_test_{int(time.time())}",
                "description": "temp — Layer 2 empty-input fast-fail test",
                "pipeline": "courseware_exam",
            },
        )
        if r.status_code != 201:
            _fail(f"POST /api/projects → {r.status_code} {r.text}")
        project_id = r.json()["id"]
        _ok(f"project_id={project_id} (no documents)")

        # ── 2. Trigger pipeline on empty project ───────────
        _step(2, "Trigger courseware_exam on empty project")
        r = client.post(
            f"/api/projects/{project_id}/pipelines/courseware_exam/runs",
            json={"input": {"user_input": "请出一套数据结构的模拟考题，覆盖每个知识点"}},
        )
        if r.status_code != 202:
            _fail(f"trigger run → {r.status_code} {r.text}")
        run_id = r.json()["run_id"]
        _ok(f"run_id={run_id}")

        # ── 3. Poll run until terminal ──────���──────────────
        _step(3, "Poll run until terminal")
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
        if detail is None:
            _fail("run poll returned no data")
        elapsed = int(time.time() - t0)

        # ── 4. Verify: run completed (not failed) ─────────
        _step(4, "Verify run status and output")

        # Empty report is a valid output, not an engine crash
        _check(
            "Run completed (not failed/cancelled)",
            detail["status"] == "completed",
            f"got status={detail['status']}, error={detail.get('error')}",
        )
        _ok(f"completed in {elapsed}s")

        # ── 5. Verify: final output contains empty signal ──
        _step(5, "Verify final output is an empty report")
        fo = detail.get("final_output", "") or ""
        print(f"      final_output length: {len(fo)}")
        if len(fo) < 500:
            print(f"      full output: {fo}")
        else:
            print(f"      head: {fo[:300]}...")

        empty_signals = ["无法生成", "无可用课件"]
        has_empty_signal = any(s in fo for s in empty_signals)
        _check(
            "Output contains empty-report signal ('无法生成' or '无可用课件')",
            has_empty_signal,
            f"neither {empty_signals} found in output",
        )

        # ── 6. Verify: no hallucinated exam content ────────
        _step(6, "Verify no hallucinated exam content")
        hallucination_markers = ["选择题", "填空题", "简答题", "论述题", "答案与解析"]
        found_markers = [m for m in hallucination_markers if m in fo]
        _check(
            "No exam content hallucinated",
            len(found_markers) == 0,
            f"found hallucinated content: {found_markers}",
        )

        # ── 7. Check intermediate outputs ──────────────────
        _step(7, "Verify intermediate node outputs")
        outputs = detail.get("outputs", {})
        for node_output, expected_signal in [
            ("parsed_content", "无可用课件"),
            ("knowledge_points", "无可用课件"),
            ("exam_draft", "无法生成"),
        ]:
            content = outputs.get(node_output, "")
            _check(
                f"{node_output} contains '{expected_signal}'",
                expected_signal in content,
                f"got: {content[:200] if content else '(empty)'}",
            )

        # ── 8. Telemetry: search_docs was called ──────────
        _step(8, "Verify search_docs was attempted")
        try:
            r = client.get(f"/api/telemetry/runs/{run_id}/timeline")
            r.raise_for_status()
            events = r.json()
            tool_calls = [e for e in events if e["event_type"] == "tool_call"]
            search_calls = [
                e for e in tool_calls
                if (e.get("payload") or {}).get("tool_name") == "search_docs"
            ]
            _check(
                "search_docs was called by parser",
                len(search_calls) >= 1,
                f"search_docs calls: {len(search_calls)}, "
                f"tools seen: {sorted({(e['payload'] or {}).get('tool_name') for e in tool_calls})}",
            )
            if search_calls:
                _ok(f"search_docs called {len(search_calls)} time(s)")

            # web_search should NOT have been called (no exam to fact-check)
            web_calls = [
                e for e in tool_calls
                if (e.get("payload") or {}).get("tool_name") == "web_search"
            ]
            _check(
                "web_search was NOT called (nothing to fact-check)",
                len(web_calls) == 0,
                f"web_search was called {len(web_calls)} time(s)",
            )
        except Exception as exc:
            print(f"      (telemetry check skipped: {exc})")

        # ── Summary ────────────────────────────────────────
        print(f"\n{'='*50}")
        print(f"Total: {passed + failed_count} | Passed: {passed} | Failed: {failed_count}")
        if failed_count:
            print("\033[31mSome checks failed.\033[0m")
            sys.exit(1)
        print("\033[32m============================================")
        print(" PASS — Layer 2 (empty-input fast-fail) verified")
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
