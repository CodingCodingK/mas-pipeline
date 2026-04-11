"""Unit tests for notify REST API (FastAPI TestClient, mocked deps)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.notify.channels.sse import SseChannel

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


class _StubNotifier:
    def __init__(self, channel_names: list[str]) -> None:
        self.channels = []
        self._sse = SseChannel()
        self.channels.append(self._sse)
        for n in channel_names:
            if n == "sse":
                continue
            self.channels.append(SimpleNamespace(name=n, deliver=AsyncMock()))


def _make_app(prefs_store: dict) -> tuple[FastAPI, _StubNotifier]:
    from src.notify.api import router as notify_router
    from src.notify import notifier as notifier_module
    from src.notify import api as api_module
    from src.notify import preferences as prefs_module

    stub = _StubNotifier(["sse", "wechat", "discord"])
    notifier_module._global_notifier = stub  # type: ignore[assignment]

    fake_user = SimpleNamespace(id=1, name="default")

    async def fake_current_user():
        return fake_user

    async def fake_get_all(user_id, session_factory):
        return {
            et: list(ch) for (uid, et), ch in prefs_store.items() if uid == user_id
        }

    async def fake_set(user_id, event_type, channels, session_factory):
        prefs_store[(user_id, event_type)] = list(channels)

    api_module.get_current_user = fake_current_user  # type: ignore[assignment]
    prefs_module.get_all = fake_get_all  # type: ignore[assignment]
    prefs_module.set = fake_set  # type: ignore[assignment]

    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(notify_router)
    app.include_router(api)
    return app, stub


def test_get_channels():
    print("\n-- GET /api/notify/channels --")
    with patch("src.api.auth.get_settings") as s:
        s.return_value.api_keys = []
        app, _ = _make_app({})
        with TestClient(app) as client:
            r = client.get("/api/notify/channels")
            check("200", r.status_code == 200)
            body = r.json()
            check("contains sse/wechat/discord", set(body) == {"sse", "wechat", "discord"})


def test_get_preferences():
    print("\n-- GET /api/notify/preferences --")
    with patch("src.api.auth.get_settings") as s:
        s.return_value.api_keys = []
        store = {(1, "run_failed"): ["sse"], (1, "run_completed"): ["sse", "wechat"]}
        app, _ = _make_app(store)
        with TestClient(app) as client:
            r = client.get("/api/notify/preferences")
            check("200", r.status_code == 200)
            body = r.json()
            check("run_failed present", body.get("run_failed") == ["sse"])
            check("run_completed present", body.get("run_completed") == ["sse", "wechat"])


def test_put_preferences_valid():
    print("\n-- PUT /api/notify/preferences (valid) --")
    with patch("src.api.auth.get_settings") as s:
        s.return_value.api_keys = []
        store: dict = {}
        app, _ = _make_app(store)
        with TestClient(app) as client:
            r = client.put(
                "/api/notify/preferences",
                json={"event_type": "run_failed", "channels": ["sse", "wechat"]},
            )
            check("200", r.status_code == 200)
            check("stored", store[(1, "run_failed")] == ["sse", "wechat"])
            body = r.json()
            check("returned map contains update", body.get("run_failed") == ["sse", "wechat"])


def test_put_preferences_bad_event_type():
    print("\n-- PUT /api/notify/preferences (bad event_type) --")
    with patch("src.api.auth.get_settings") as s:
        s.return_value.api_keys = []
        store: dict = {}
        app, _ = _make_app(store)
        with TestClient(app) as client:
            r = client.put(
                "/api/notify/preferences",
                json={"event_type": "unknown", "channels": ["sse"]},
            )
            check("400", r.status_code == 400)
            check("store unchanged", store == {})


def test_put_preferences_bad_channel():
    print("\n-- PUT /api/notify/preferences (bad channel) --")
    with patch("src.api.auth.get_settings") as s:
        s.return_value.api_keys = []
        store: dict = {}
        app, _ = _make_app(store)
        with TestClient(app) as client:
            r = client.put(
                "/api/notify/preferences",
                json={"event_type": "run_failed", "channels": ["pagerduty"]},
            )
            check("400", r.status_code == 400)
            check("store unchanged", store == {})


def test_stream_requires_api_key():
    print("\n-- GET /api/notify/stream (auth) --")
    with patch("src.api.auth.get_settings") as s:
        s.return_value.api_keys = ["secret"]
        app, _ = _make_app({})
        with TestClient(app) as client:
            r = client.get("/api/notify/stream")
            check("401 without key", r.status_code == 401)


def test_stream_generator_yields_notification():
    """Test the SSE generator directly, bypassing httpx/TestClient buffering.

    TestClient + ASGITransport deadlock on infinite SSE generators (same
    pattern as Phase 6.1's backfill_events_from extraction). We unit-test
    the generator body by calling the route function and pulling frames
    from the StreamingResponse's body_iterator.
    """
    print("\n-- notify_stream generator yields notification --")
    import asyncio as _asyncio

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
        app, stub = _make_app({})

        class _FakeRequest:
            async def is_disconnected(self):
                return False

        async def _run():
            response = await api_module.notify_stream(_FakeRequest())
            body_iter = response.body_iterator
            # Pre-register a queue as the route did and deliver into it.
            # The route already registered its own queue, which we access
            # via the stub SSE channel.
            sse = stub._sse
            # There is exactly one registered queue for user_id=1 right now.
            q = sse._queues[1][0]
            await q.put(
                Notification(
                    event_type="run_completed",
                    user_id=1,
                    title="ok",
                    body="b",
                    payload={},
                )
            )
            frame = await _asyncio.wait_for(body_iter.__anext__(), timeout=3.0)
            # Close the generator so the finally-unregister fires.
            await body_iter.aclose()
            return frame

        frame = _asyncio.new_event_loop().run_until_complete(_run())
        check("frame has event: line", "event: run_completed" in frame)
        check("frame has data: line", "data:" in frame)
    finally:
        config_module.get_settings = original_get_settings  # type: ignore[attr-defined]
        api_module.get_settings = original_get_settings  # type: ignore[attr-defined]


def main() -> int:
    test_get_channels()
    test_get_preferences()
    test_put_preferences_valid()
    test_put_preferences_bad_event_type()
    test_put_preferences_bad_channel()
    test_stream_requires_api_key()
    test_stream_generator_yields_notification()
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
