"""Unit test for src.api.metrics — isolated, no DB / no compose.

Verifies:
- All 5 metric names appear in generate_latest()
- sse_connect/sse_disconnect move the sse_connections gauge
- messages_total counter monotonically increases on bus emit
"""

from __future__ import annotations

import sys

from prometheus_client import generate_latest

from src.api.metrics import (
    messages_total,
    sessions_active,
    sse_connect,
    sse_connections,
    sse_disconnect,
    workers_running,
    pg_connections_used,
    _sse_current,
)


def _check(name: str, ok: bool) -> None:
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}")
    if not ok:
        sys.exit(1)


def main() -> None:
    # 1. All five metric names present in the default registry output.
    output = generate_latest().decode("utf-8")
    for name in (
        "sessions_active",
        "workers_running",
        "pg_connections_used",
        "sse_connections",
        "messages_total",
    ):
        _check(f"metric '{name}' present", name in output)

    # 2. HELP + TYPE lines present for each.
    _check("HELP line for sessions_active", "# HELP sessions_active" in output)
    _check("TYPE gauge for sessions_active", "# TYPE sessions_active gauge" in output)
    _check("TYPE counter for messages_total", "# TYPE messages_total counter" in output)

    # 3. sse_connect / sse_disconnect adjust the internal counter.
    before = _sse_current()
    sse_connect()
    sse_connect()
    _check("sse_connect increments", _sse_current() == before + 2)
    sse_disconnect()
    sse_disconnect()
    _check("sse_disconnect decrements", _sse_current() == before)

    # 4. sse_disconnect clamps at zero.
    for _ in range(10):
        sse_disconnect()
    _check("sse_disconnect clamps at 0", _sse_current() >= 0)

    # 5. messages_total is monotonic across emit.
    from src.events.bus import EventBus
    bus = EventBus()
    bus.subscribe("test", max_size=10)
    start_val = messages_total._value.get()  # type: ignore[attr-defined]
    for _ in range(5):
        bus.emit({"type": "noop"})
    end_val = messages_total._value.get()  # type: ignore[attr-defined]
    _check("messages_total >= +5 after 5 emits", end_val >= start_val + 5)
    _check("messages_total monotonic", end_val >= start_val)

    print("\nAll metrics tests passed.")


if __name__ == "__main__":
    main()
