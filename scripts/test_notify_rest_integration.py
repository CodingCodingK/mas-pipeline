"""Notify REST integration tests: FastAPI TestClient + real PG.

Seeds a user and preferences via SQL, exercises `PUT /api/notify/preferences`
and `GET /api/notify/preferences` against the real DB, and exercises
`GET /api/notify/stream` by pulling one frame directly from the endpoint's
generator (bypassing httpx buffering — same pattern as unit test).

Skips gracefully if PG is not reachable.
"""

from __future__ import annotations

import asyncio
import platform
import sys
from pathlib import Path
from types import SimpleNamespace

if platform.system() == "Windows":
    import selectors  # noqa: F401
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.db import get_db

passed = 0
failed = 0
skipped = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def skip_all(reason: str) -> None:
    global skipped
    skipped += 1
    print(f"  [SKIP] {reason}")


async def _seed() -> None:
    async with get_db() as session:
        await session.execute(
            text(
                "CREATE TABLE IF NOT EXISTS user_notify_preferences ("
                "user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "event_type TEXT NOT NULL, "
                "channels JSONB NOT NULL, "
                "updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), "
                "PRIMARY KEY (user_id, event_type))"
            )
        )
        await session.execute(
            text(
                "INSERT INTO users (id, name, email) "
                "VALUES (102, 'notif-rest', 'r@e.com') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )
        await session.execute(
            text("DELETE FROM user_notify_preferences WHERE user_id = 102")
        )
        await session.commit()


async def _cleanup() -> None:
    async with get_db() as session:
        await session.execute(
            text("DELETE FROM user_notify_preferences WHERE user_id = 102")
        )
        await session.commit()


def _make_app_with_stub_user():
    from src.notify.api import router as notify_router
    from src.notify import api as api_module
    from src.notify import notifier as notifier_module
    from src.notify.channels.sse import SseChannel

    fake_user = SimpleNamespace(id=102, name="notif-rest")

    async def fake_current_user():
        return fake_user

    api_module.get_current_user = fake_current_user  # type: ignore[assignment]

    stub = SimpleNamespace(channels=[SseChannel()])
    notifier_module._global_notifier = stub  # type: ignore[assignment]

    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(notify_router)
    app.include_router(api)
    return app, stub


def test_preferences_crud() -> None:
    print("\n=== PUT/GET /api/notify/preferences (real PG) ===")
    app, _ = _make_app_with_stub_user()
    from unittest.mock import patch

    with patch("src.api.auth.get_settings") as s:
        s.return_value.api_keys = []
        with TestClient(app) as client:
            r = client.put(
                "/api/notify/preferences",
                json={"event_type": "run_failed", "channels": ["sse"]},
            )
            check("PUT 200", r.status_code == 200)
            r2 = client.get("/api/notify/preferences")
            check("GET 200", r2.status_code == 200)
            body = r2.json()
            check("run_failed=[sse]", body.get("run_failed") == ["sse"])


async def test_stream_generator_delivers_notification() -> None:
    print("\n=== notify_stream generator (real PG-backed prefs) ===")
    app, stub = _make_app_with_stub_user()
    from src.notify import api as api_module
    from src.notify.events import Notification
    from src.project import config as config_module

    original_get_settings = config_module.get_settings

    def fake_get_settings():
        s = original_get_settings()
        s.notify.sse_heartbeat_sec = 1
        return s

    config_module.get_settings = fake_get_settings  # type: ignore[attr-defined]
    api_module.get_settings = fake_get_settings  # type: ignore[attr-defined]
    try:
        class _FakeRequest:
            async def is_disconnected(self):
                return False

        async def _run():
            response = await api_module.notify_stream(_FakeRequest())
            body_iter = response.body_iterator
            sse = stub.channels[0]
            q = sse._queues[102][0]
            await q.put(
                Notification(
                    event_type="run_completed",
                    user_id=102,
                    title="t",
                    body="b",
                    payload={"run_id": "x"},
                )
            )
            frame = await asyncio.wait_for(body_iter.__anext__(), timeout=3.0)
            await body_iter.aclose()
            return frame

        frame = await _run()
        check("frame contains event: run_completed", "event: run_completed" in frame)
        check("frame contains data:", "data:" in frame)
    finally:
        config_module.get_settings = original_get_settings  # type: ignore[attr-defined]
        api_module.get_settings = original_get_settings  # type: ignore[attr-defined]


async def main_async() -> None:
    try:
        await _seed()
    except Exception as exc:  # noqa: BLE001
        skip_all(f"DB not reachable: {type(exc).__name__}: {exc}")
        return
    try:
        test_preferences_crud()
        await test_stream_generator_delivers_notification()
    finally:
        await _cleanup()


def main() -> None:
    asyncio.run(main_async())
    print(f"\n{'=' * 50}")
    print(f"Results: {passed} passed, {failed} failed, {skipped} skipped")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
