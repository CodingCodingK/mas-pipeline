"""REST tests for src/api/pipelines.py (Change 2 / Phase 6.4 step 4).

No PG — uses tmpdir + TestClient. Pipeline DELETE has no reference check,
so there's no 409 case (unlike agents).

Run: python scripts/test_rest_pipelines.py
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

from src.api.pipelines import router as pipelines_router
from src.storage import layered as layered_mod

passed = 0
failed = 0

PIPE_YAML = "pipeline: blog\nnodes:\n  - name: w\n    role: writer\n"


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
    app.include_router(pipelines_router, prefix="/api")
    return app


def fresh_root() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="rest_pipes_"))
    layered_mod._ROOT = tmp
    return tmp


def teardown(tmp: Path) -> None:
    shutil.rmtree(tmp, ignore_errors=True)


def _client() -> TestClient:
    return TestClient(_build_app())


def test_global_crud():
    section("global pipeline CRUD")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                r = c.put("/api/pipelines/blog", json={"content": PIPE_YAML})
                check("PUT create → 201", r.status_code == 201)

                r = c.put("/api/pipelines/blog", json={"content": PIPE_YAML})
                check("PUT overwrite → 200", r.status_code == 200)

                r = c.get("/api/pipelines/blog")
                check("GET 200", r.status_code == 200)
                body = r.json()
                check("GET name", body["name"] == "blog")
                check("GET content has role: writer", "role: writer" in body["content"])
                check("GET source=global", body["source"] == "global")

                r = c.get("/api/pipelines")
                check("list 200", r.status_code == 200)
                items = r.json()["items"]
                check("list has blog", any(i["name"] == "blog" for i in items))

                # DELETE — never blocks, no reference check
                r = c.delete("/api/pipelines/blog")
                check("DELETE 204", r.status_code == 204)

                r = c.get("/api/pipelines/blog")
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
                r = c.get("/api/pipelines/a.b")
                check("GET invalid → 422", r.status_code == 422)
                r = c.put("/api/pipelines/a.b", json={"content": "x"})
                check("PUT invalid → 422", r.status_code == 422)
                r = c.delete("/api/pipelines/a.b")
                check("DELETE invalid → 422", r.status_code == 422)
    finally:
        teardown(tmp)


def test_global_404():
    section("global 404 on missing")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                r = c.get("/api/pipelines/nobody")
                check("GET missing → 404", r.status_code == 404)
                r = c.delete("/api/pipelines/nobody")
                check("DELETE missing → 404", r.status_code == 404)
    finally:
        teardown(tmp)


def test_global_legacy_variant():
    section("global legacy _generation variant resolves")
    tmp = fresh_root()
    try:
        (tmp / "pipelines").mkdir()
        (tmp / "pipelines" / "blog_generation.yaml").write_text(PIPE_YAML, encoding="utf-8")
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                r = c.get("/api/pipelines/blog")
                check("legacy fallback → 200", r.status_code == 200, r.text)
                check("content returned", "role: writer" in r.json()["content"])
    finally:
        teardown(tmp)


def test_project_crud_merged_view():
    section("project CRUD + merged view")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = []
            with _client() as c:
                # Global: 'blog' and 'report'
                c.put("/api/pipelines/blog", json={"content": PIPE_YAML})
                c.put("/api/pipelines/report", json={"content": PIPE_YAML})
                # Project 42: override blog, add 'local'
                r = c.put("/api/projects/42/pipelines/blog", json={"content": PIPE_YAML})
                check("project PUT override → 201", r.status_code == 201)
                r = c.put("/api/projects/42/pipelines/local", json={"content": PIPE_YAML})
                check("project PUT new → 201", r.status_code == 201)

                r = c.get("/api/projects/42/pipelines")
                check("merged view 200", r.status_code == 200)
                items = {i["name"]: i["source"] for i in r.json()["items"]}
                check("blog is project-override", items.get("blog") == "project-override")
                check("report is global", items.get("report") == "global")
                check("local is project-only", items.get("local") == "project-only")

                r = c.get("/api/projects/42/pipelines/blog")
                check("effective blog source=project", r.json()["source"] == "project")

                r = c.get("/api/projects/42/pipelines/report")
                check("effective report source=global", r.json()["source"] == "global")

                r = c.delete("/api/projects/42/pipelines/blog")
                check("project DELETE 204", r.status_code == 204)

                r = c.get("/api/projects/42/pipelines/blog")
                check("after delete falls back to global", r.json()["source"] == "global")

                r = c.delete("/api/projects/42/pipelines/nobody")
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
                r = c.put("/api/projects/1/pipelines/a.b", json={"content": "x"})
                check("PUT invalid → 422", r.status_code == 422)
                r = c.delete("/api/projects/1/pipelines/a.b")
                check("DELETE invalid → 422", r.status_code == 422)
                r = c.get("/api/projects/1/pipelines/a.b")
                check("GET invalid → 422", r.status_code == 422)
    finally:
        teardown(tmp)


def test_auth_required():
    section("401 when API key required")
    tmp = fresh_root()
    try:
        with patch("src.api.auth.get_settings") as gs:
            gs.return_value.api_keys = ["secret"]
            with _client() as c:
                r = c.get("/api/pipelines")
                check("no header → 401", r.status_code == 401)
                r = c.get("/api/pipelines", headers={"X-API-Key": "wrong"})
                check("bad key → 401", r.status_code == 401)
                r = c.get("/api/pipelines", headers={"X-API-Key": "secret"})
                check("good key → 200", r.status_code == 200)
    finally:
        teardown(tmp)


def main() -> None:
    original_root = layered_mod._ROOT
    try:
        test_global_crud()
        test_global_invalid_name()
        test_global_404()
        test_global_legacy_variant()
        test_project_crud_merged_view()
        test_project_invalid_name()
        test_auth_required()
    finally:
        layered_mod._ROOT = original_root

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
