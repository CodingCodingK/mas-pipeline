"""Hit /metrics against a running API and assert all 5 metric names appear.

Usage (requires compose stack up):
    python scripts/test_metrics_http.py
    python scripts/test_metrics_http.py --url http://localhost/metrics
"""

from __future__ import annotations

import argparse
import sys
import urllib.request


REQUIRED = (
    "sessions_active",
    "workers_running",
    "pg_connections_used",
    "sse_connections",
    "messages_total",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000/metrics")
    args = parser.parse_args()

    try:
        with urllib.request.urlopen(args.url, timeout=5) as resp:
            ctype = resp.headers.get("Content-Type", "")
            body = resp.read().decode("utf-8")
    except Exception as exc:
        print(f"FAIL: cannot reach {args.url}: {exc}")
        sys.exit(1)

    if "text/plain" not in ctype:
        print(f"FAIL: unexpected Content-Type: {ctype}")
        sys.exit(1)

    missing = [name for name in REQUIRED if name not in body]
    if missing:
        print(f"FAIL: missing metric names: {missing}")
        sys.exit(1)

    for name in REQUIRED:
        print(f"[OK] {name}")
    print(f"\n/metrics at {args.url} exposes all 5 metrics.")


if __name__ == "__main__":
    main()
