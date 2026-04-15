"""End-to-end smoke for Phase 收尾 4.1 (permission + MCP github activation).

Exercises three things against a running compose stack:

  A. assistant writes to projects/<id>/outputs/smoke.txt → success, file on disk
  B. assistant writes to src/evil.py           → permission denied, no file
  C. telemetry timeline for the session shows at least one permission_denied
     marker on the src/evil.py attempt
  D. (best-effort) MCP github tools were registered at SessionRunner.start —
     checked by looking for a tool_call whose name starts with `github:` in
     any recent blog_generation run. Skipped with WARN if not reachable.

Usage:
    python scripts/test_permission_mcp_smoke.py
    python scripts/test_permission_mcp_smoke.py --base http://localhost:8000 --api-key KEY
    python scripts/test_permission_mcp_smoke.py --keep     # leave project
    python scripts/test_permission_mcp_smoke.py --skip-d   # skip github step

Exits 0 on success, non-zero with a red reason on failure. Step D failures
print YELLOW WARN and do NOT fail the run (LLM-dependent).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


RED = "\033[31m"
GRN = "\033[32m"
YEL = "\033[33m"
RST = "\033[0m"


def _fail(msg: str) -> None:
    print(f"\n{RED}FAIL: {msg}{RST}")
    sys.exit(1)


def _warn(msg: str) -> None:
    print(f"  {YEL}[WARN] {msg}{RST}")


def _ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def _step(n: str, msg: str) -> None:
    print(f"\n[{n}] {msg}")


def _wait_for_reply(client: httpx.Client, session_id: int, baseline: int,
                    timeout: float = 180.0) -> list[dict]:
    """Poll /sessions/{id}/messages until a new assistant message appears."""
    deadline = time.time() + timeout
    last_total = baseline
    while time.time() < deadline:
        r = client.get(
            f"/api/sessions/{session_id}/messages",
            params={"offset": 0, "limit": 500},
        )
        r.raise_for_status()
        page = r.json()
        total = page["total"]
        if total > last_total:
            # Look for a new assistant turn after baseline
            new = page["items"][baseline:]
            if any(m.get("role") == "assistant" for m in new):
                return new
            last_total = total
        time.sleep(1.5)
    _fail(f"timed out waiting for assistant reply on session {session_id}")
    return []  # unreachable


def _session_timeline(client: httpx.Client, session_id: int) -> list[dict]:
    """Full telemetry timeline for a chat session (run_id=session-<id>)."""
    r = client.get(f"/api/telemetry/runs/session-{session_id}/timeline")
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json()


def _tool_calls_for_session(client: httpx.Client, session_id: int) -> list[dict]:
    return [e for e in _session_timeline(client, session_id) if e.get("event_type") == "tool_call"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.getenv("API_BASE", "http://localhost:8000"))
    parser.add_argument("--api-key", default=os.getenv("API_KEY", ""))
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--skip-d", action="store_true",
                        help="Skip the github MCP best-effort check")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    client = httpx.Client(base_url=base, headers=headers, timeout=60.0)

    # ── 0. Health ──
    _step("0", "Health check")
    try:
        r = client.get("/health")
        r.raise_for_status()
    except Exception as exc:
        _fail(f"cannot reach {base}/health: {exc}")
    _ok(f"{base}/health → {r.status_code}")

    project_id = None
    try:
        # ── 1. Create project ──
        _step("1", "Create project")
        r = client.post(
            "/api/projects",
            json={
                "name": f"perm_mcp_smoke_{int(time.time())}",
                "description": "temp — permission + MCP github smoke",
                "pipeline": "blog_generation",
            },
        )
        if r.status_code != 201:
            _fail(f"POST /api/projects → {r.status_code} {r.text}")
        project_id = r.json()["id"]
        _ok(f"project_id={project_id}")

        # ── 2. Create chat session (assistant mode) ──
        _step("2", "Create assistant chat session")
        r = client.post(
            f"/api/projects/{project_id}/sessions",
            json={"mode": "chat", "channel": "smoke", "chat_id": f"t{int(time.time())}"},
        )
        if r.status_code != 201:
            _fail(f"POST sessions → {r.status_code} {r.text}")
        session_id = r.json()["id"]
        _ok(f"session_id={session_id}")

        good_rel = f"projects/{project_id}/outputs/smoke.txt"
        bad_rel = "src/evil.py"

        # ── A. Allowed write ──
        _step("A", f"assistant writes to {good_rel}")
        prompt_a = (
            f"Please call the write_file tool exactly once with "
            f"file_path='{good_rel}' and content='hello smoke'. "
            f"After calling it, reply 'done'."
        )
        r = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"content": prompt_a},
        )
        if r.status_code != 202:
            _fail(f"send A → {r.status_code} {r.text}")
        baseline_a = r.json()["message_index"] + 1
        _wait_for_reply(client, session_id, baseline_a)

        good_abs = Path.cwd() / good_rel
        if good_abs.exists():
            _ok(f"{good_rel} exists on disk ({good_abs.stat().st_size} bytes)")
        else:
            _warn(f"{good_rel} not on disk here — expected on server filesystem, "
                  f"not the host running this script. Relying on telemetry check.")

        # args_preview is truncated to 30 chars by telemetry, so match on tool_name +
        # success; session isolation makes this unambiguous within one test run.
        tcs = _tool_calls_for_session(client, session_id)
        write_a = [
            e for e in tcs
            if (e.get("payload") or {}).get("tool_name") == "write_file"
            and (e.get("payload") or {}).get("success")
        ]
        if not write_a:
            all_wf = [e for e in tcs if (e.get("payload") or {}).get("tool_name") == "write_file"]
            _fail(f"no successful write_file tool_call in session {session_id}. "
                  f"write_file calls seen: {len(all_wf)}; last payload: "
                  f"{all_wf[-1].get('payload') if all_wf else None}")
        _ok(f"write_file succeeded ({len(write_a)} call(s))")

        # ── B. Denied write ──
        _step("B", f"assistant writes to {bad_rel}")
        prompt_b = (
            f"Now call write_file with file_path='{bad_rel}' and "
            f"content='exploit()'. Then reply 'done' regardless of outcome."
        )
        r = client.post(
            f"/api/sessions/{session_id}/messages",
            json={"content": prompt_b},
        )
        if r.status_code != 202:
            _fail(f"send B → {r.status_code} {r.text}")
        baseline_b = r.json()["message_index"] + 1
        _wait_for_reply(client, session_id, baseline_b)

        bad_abs = Path.cwd() / bad_rel
        if bad_abs.exists():
            # If we're on the host and a previous commit created src/evil.py
            # that's a real failure. Otherwise noop.
            if "exploit" in bad_abs.read_text(encoding="utf-8", errors="replace"):
                _fail(f"{bad_rel} got written on disk — permission bypass!")
            else:
                _warn(f"{bad_rel} already existed for unrelated reasons")
        else:
            _ok(f"{bad_rel} does not exist on disk")

        # ── C. Telemetry denial marker ──
        # Permission denial fires at the pre_tool_use hook, BEFORE the tool
        # executes. The denial lands in a `hook_event` row with decision=deny
        # and rule_matched containing the rule text — not in a `tool_call` row.
        _step("C", "Telemetry: permission_denied marker")
        events = _session_timeline(client, session_id)
        denied = []
        for e in events:
            if e.get("event_type") != "hook_event":
                continue
            p = e.get("payload") or {}
            if p.get("hook_type") != "pre_tool_use":
                continue
            if p.get("decision") != "deny":
                continue
            rule = (p.get("rule_matched") or "").lower()
            if "write_file" in rule or "src/" in rule:
                denied.append(e)
        if not denied:
            all_hooks = [
                (e.get("payload") or {})
                for e in events
                if e.get("event_type") == "hook_event"
            ]
            _fail(f"no pre_tool_use deny hook_event in session {session_id}. "
                  f"Hook events seen: {len(all_hooks)}; decisions: "
                  f"{[h.get('decision') for h in all_hooks]}")
        _ok(f"{len(denied)} pre_tool_use deny hook(s) matched (rule: "
            f"{(denied[0].get('payload') or {}).get('rule_matched')})")

        # ── D. github MCP best-effort ──
        if args.skip_d:
            _step("D", "skipped via --skip-d")
        else:
            _step("D", "MCP github tool registration (best-effort)")
            # Easiest signal: look for any 'github:*' tool call in any recent run.
            # In most test runs this will be empty (no pipeline triggered it), so
            # we downgrade to WARN, not FAIL.
            r = client.get("/api/runs", params={"limit": 20})
            found_github = False
            if r.status_code == 200:
                runs = r.json() if isinstance(r.json(), list) else r.json().get("items", [])
                for run in runs[:20]:
                    rid = run.get("id") or run.get("run_id")
                    if not rid:
                        continue
                    rr = client.get(f"/api/telemetry/runs/{rid}/timeline")
                    if rr.status_code != 200:
                        continue
                    for e in rr.json():
                        name = (e.get("payload") or {}).get("tool_name") or ""
                        if name.startswith("github:") or name.startswith("github_"):
                            found_github = True
                            break
                    if found_github:
                        break
            if found_github:
                _ok("observed github:* tool_call in recent telemetry")
            else:
                _warn("no github:* tool_call seen in recent runs — "
                      "cannot confirm MCP server registered tools via telemetry. "
                      "Check SessionRunner log line 'MCPManager started with N tools' instead.")

        print(f"\n{GRN}============================================")
        print(" PASS — 收尾 4.1 permission + MCP smoke")
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
