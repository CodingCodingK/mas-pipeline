"""REST tests for src/api/agents.py (Change 2 / Phase 6.4 step 4).

No PG — uses tmpdir + TestClient. Monkey-patches `src.storage.layered._ROOT`
to isolate each test block.

Run: python scripts/test_rest_agents.py
"""

from __future__ import annotations

import asyncio
import platform
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.agents import router as agents_router
from src.storage import layered as layered_mod

passed = 0
failed = 0


def section(name: str) -> None:
    print(f"\n=== {name} ===")


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(agents_router, prefix="/api")
    return app


def fresh_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="rest_agents_"))
    layered_mod._ROOT = tmp
    return tmp


def teardown(tmp: Path) -> None:
    shutil.rmtree(tmp, ignore_errors=True)


def _client() -> TestClient:
    return TestClient(_build_app())


# ── Global layer ───────────────────────────────────────────

def test_global_crud():
    section("global agent CRUD")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                # PUT create
                r = c.put("/api/agents/writer", json={"content": "# writer"})
                check("PUT create → 201", r.status_code == 201, r.text)

                # PUT overwrite
                r = c.put("/api/agents/writer", json={"content": "# writer v2"})
                check("PUT overwrite → 200", r.status_code == 200)

                # GET read
                r = c.get("/api/agents/writer")
                check("GET 200", r.status_code == 200)
                body = r.json()
                check("GET body name", body["name"] == "writer")
                check("GET body content", body["content"] == "# writer v2")
                check("GET body source=global", body["source"] == "global")

                # GET list
                r = c.get("/api/agents")
                check("list 200", r.status_code == 200)
                items = r.json()["items"]
                check("list has writer", any(i["name"] == "writer" for i in items))

                # DELETE
                r = c.delete("/api/agents/writer")
                check("DELETE 204", r.status_code == 204)

                # GET 404
                r = c.get("/api/agents/writer")
                check("GET after delete 404", r.status_code == 404)
    finally:
        teardown(tmp)


def test_global_invalid_name():
    section("global invalid name → 422")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                r = c.get("/api/agents/a.b")
                check("GET invalid → 422", r.status_code == 422, r.text)

                r = c.put("/api/agents/a.b", json={"content": "x"})
                check("PUT invalid → 422", r.status_code == 422)

                r = c.delete("/api/agents/a.b")
                check("DELETE invalid → 422", r.status_code == 422)
    finally:
        teardown(tmp)


def test_global_delete_blocked():
    section("global delete blocked by reference → 409")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                c.put("/api/agents/writer", json={"content": "G"})
                # Create global pipeline referencing writer (via file system directly)
                (tmp / "pipelines").mkdir(exist_ok=True)
                (tmp / "pipelines" / "blog.yaml").write_text(
                    "pipeline: blog\nnodes:\n  - name: w\n    role: writer\n",
                    encoding="utf-8",
                )

                r = c.delete("/api/agents/writer")
                check("DELETE referenced → 409", r.status_code == 409, r.text)
                body = r.json()
                # FastAPI wraps a dict detail at top-level "detail"
                detail = body.get("detail", {})
                check("409 body has references", "references" in detail, str(body))
                refs = detail.get("references", [])
                check("references non-empty", len(refs) >= 1, str(refs))
                check("global file still present", (tmp / "agents" / "writer.md").is_file())
    finally:
        teardown(tmp)


def test_global_404():
    section("global 404 on missing")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                r = c.get("/api/agents/nobody")
                check("GET missing → 404", r.status_code == 404)
                r = c.delete("/api/agents/nobody")
                check("DELETE missing → 404", r.status_code == 404)
    finally:
        teardown(tmp)


# ── Project layer ──────────────────────────────────────────

def test_project_crud_merged_view():
    section("project CRUD + merged view")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                # Seed: global 'writer' + 'researcher'
                c.put("/api/agents/writer", json={"content": "G"})
                c.put("/api/agents/researcher", json={"content": "G"})
                # Project 42: override writer, add analyst
                r = c.put("/api/projects/42/agents/writer", json={"content": "P"})
                check("project PUT create → 201", r.status_code == 201)
                r = c.put("/api/projects/42/agents/analyst", json={"content": "P"})
                check("project PUT analyst → 201", r.status_code == 201)

                # Merged view
                r = c.get("/api/projects/42/agents")
                check("merged view 200", r.status_code == 200)
                items = {i["name"]: i["source"] for i in r.json()["items"]}
                check("writer is project-override", items.get("writer") == "project-override")
                check("researcher is global", items.get("researcher") == "global")
                check("analyst is project-only", items.get("analyst") == "project-only")

                # Effective read (project layer)
                r = c.get("/api/projects/42/agents/writer")
                check("effective read writer", r.status_code == 200)
                body = r.json()
                check("effective writer content=P", body["content"] == "P")
                check("effective writer source=project", body["source"] == "project")

                # Effective read (falls through to global)
                r = c.get("/api/projects/42/agents/researcher")
                check("effective read researcher 200", r.status_code == 200)
                check("researcher source=global", r.json()["source"] == "global")

                # Delete project override
                r = c.delete("/api/projects/42/agents/writer")
                check("project DELETE 204", r.status_code == 204)

                # After delete: writer falls back to global
                r = c.get("/api/projects/42/agents/writer")
                check("after project delete → global", r.json()["source"] == "global")

                # Delete missing project agent
                r = c.delete("/api/projects/42/agents/nobody")
                check("project DELETE missing → 404", r.status_code == 404)
    finally:
        teardown(tmp)


def test_project_invalid_name():
    section("project invalid name → 422")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                r = c.put("/api/projects/1/agents/a.b", json={"content": "x"})
                check("PUT invalid → 422", r.status_code == 422)
                r = c.delete("/api/projects/1/agents/a.b")
                check("DELETE invalid → 422", r.status_code == 422)
                r = c.get("/api/projects/1/agents/a.b")
                check("GET invalid → 422", r.status_code == 422)
    finally:
        teardown(tmp)


# ── Auth ──────────────────────────────────────────────────

def test_auth_required():
    section("401 when API key required")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = ["secret"]
            with _client() as c:
                r = c.get("/api/agents")
                check("no header → 401", r.status_code == 401)
                r = c.get("/api/agents", headers={"X-API-Key": "wrong"})
                check("bad key → 401", r.status_code == 401)
                r = c.get("/api/agents", headers={"X-API-Key": "secret"})
                check("good key → 200", r.status_code == 200)
    finally:
        teardown(tmp)


def main() -> None:
    original_root = layered_mod._ROOT
    try:
        test_global_crud()
        test_global_invalid_name()
        test_global_delete_blocked()
        test_global_404()
        test_project_crud_merged_view()
        test_project_invalid_name()
        test_auth_required()
    finally:
        layered_mod._ROOT = original_root

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
