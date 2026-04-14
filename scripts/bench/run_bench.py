"""Benchmark harness — drive scenarios and snapshot 6-dim telemetry.

Design
------
The harness is deliberately thin: each scenario is a coroutine that does
whatever it takes to generate telemetry rows (start a session, trigger a
pipeline, spawn agents, etc.) and returns a pair of ``(since, until)``
timestamps bracketing its activity. The harness then asks
``src/bench/queries.py`` for the six dimensions filtered by that window
and writes the result to ``.plan/benchmarks/{timestamp}_{scenario}.json``.

Run
---
    # collect-only: snapshot last N minutes of whatever's already in PG
    python scripts/bench/run_bench.py collect --minutes 30

    # single scenario (fake LLM path via test_e2e_smoke.py subprocess)
    python scripts/bench/run_bench.py run --scenario blog_with_review --provider mock

    # run everything available in mock mode
    python scripts/bench/run_bench.py all --provider mock

Mock mode reuses ``scripts/test_e2e_smoke.py``'s embedded fake LLM so the
harness itself never talks to a real provider. Real mode assumes the
shipped settings.yaml is already pointing at a real provider — the harness
does not swap credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Windows catch-22: psycopg requires SelectorEventLoop, but asyncio's
# create_subprocess_exec only works on ProactorEventLoop. We keep the
# Selector policy (so PG works) and shell out via plain subprocess.run
# inside asyncio.to_thread for the scenario drivers.
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.bench import queries
from src.db import get_db  # noqa: E402

BENCH_DIR = Path(".plan/benchmarks")


# ── Shared helpers ─────────────────────────────────────────────────


async def _snapshot(
    scenario: str,
    since: datetime,
    until: datetime,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    provider: str,
    extra: dict | None = None,
) -> Path:
    """Query 6 dimensions for [since, until) and write a JSON snapshot."""
    # Retry loop: PG may still be warming up after a compose restart.
    last_exc: Exception | None = None
    for attempt in range(6):
        try:
            async with get_db() as session:
                dims = await queries.all_dimensions(
                    session,
                    project_id=project_id,
                    run_id=run_id,
                    since=since,
                    until=until,
                )
            break
        except Exception as exc:
            last_exc = exc
            print(f"[bench] snapshot attempt {attempt + 1}/6 failed: {exc!r}")
            await asyncio.sleep(5)
    else:
        raise RuntimeError(f"snapshot failed after retries: {last_exc!r}")

    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{stamp}_{scenario}_{provider}.json"
    path = BENCH_DIR / filename
    payload = {
        "scenario": scenario,
        "provider": provider,
        "since": since.isoformat(),
        "until": until.isoformat(),
        "project_id": project_id,
        "run_id": run_id,
        "dimensions": dims,
        "extra": extra or {},
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[bench] wrote {path}")
    return path


# ── Scenarios ──────────────────────────────────────────────────────


async def scenario_collect(minutes: int, *, provider: str) -> Path:
    """No-op driver: snapshot the last N minutes of telemetry as-is.

    Useful when you've already driven traffic through some other route
    (smoke test, manual pipeline run) and just want the numbers pulled out.
    """
    until = datetime.now(timezone.utc)
    since = until - timedelta(minutes=minutes)
    return await _snapshot("collect", since, until, provider=provider)


async def scenario_blog_with_review(provider: str) -> Path:
    """Drive blog_with_review via scripts/test_e2e_smoke.py (fake LLM).

    The smoke script owns the compose stack + fake LLM lifecycle. We just
    record the wall-clock bracket and let the snapshot query catch every
    telemetry row that landed during that window.
    """
    if provider != "mock":
        print(
            "[bench] WARN: blog_with_review scenario currently only ships "
            "a mock driver (test_e2e_smoke.py). Skipping for provider=" + provider
        )
        return await _snapshot(
            "blog_with_review", datetime.now(timezone.utc),
            datetime.now(timezone.utc), provider=provider,
            extra={"skipped": "real driver not implemented"},
        )

    since = datetime.now(timezone.utc)
    driver = Path("scripts") / "test_e2e_smoke.py"
    print(f"[bench] launching {driver} ...")

    def _run_driver() -> int:
        proc = subprocess.Popen(
            [sys.executable, str(driver)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print("  " + line.rstrip())
        return proc.wait()

    rc = await asyncio.to_thread(_run_driver)
    until = datetime.now(timezone.utc)
    # test_e2e_smoke.py tears down its compose stack on exit, which takes
    # down PG too. Bring the dev stack back up before the snapshot query.
    print("[bench] restoring dev compose stack for snapshot query ...")
    await asyncio.to_thread(
        subprocess.run, ["docker", "compose", "up", "-d"],
        check=False,
    )
    # PG healthcheck: retry the snapshot query loop a few times if needed.
    return await _snapshot(
        "blog_with_review", since, until,
        provider=provider,
        extra={"driver": "test_e2e_smoke.py", "return_code": rc},
    )


async def scenario_long_chat(provider: str) -> Path:
    """Compact trigger scenario — placeholder.

    Requires a long chat session that pushes the context window past the
    autocompact threshold. Real implementation: post N turns via
    POST /api/sessions/{id}/messages and wait for the assistant reply.
    For now, this function just records a sentinel snapshot so the report
    renderer has a slot to fill in; implement when chat REST driver is ready.
    """
    now = datetime.now(timezone.utc)
    return await _snapshot(
        "long_chat", now, now, provider=provider,
        extra={"status": "not_implemented", "todo": "drive chat via REST"},
    )


async def scenario_rag_courseware(provider: str) -> Path:
    """RAG retrieval scenario — delegates to scripts/test_rag_e2e.py if present."""
    driver = Path("scripts") / "test_rag_e2e.py"
    if not driver.exists():
        now = datetime.now(timezone.utc)
        return await _snapshot(
            "rag_courseware", now, now, provider=provider,
            extra={"status": "driver_missing"},
        )
    if provider != "real":
        now = datetime.now(timezone.utc)
        return await _snapshot(
            "rag_courseware", now, now, provider=provider,
            extra={"status": "skipped", "reason": "needs real LLM"},
        )
    since = datetime.now(timezone.utc)
    print(f"[bench] launching {driver} ...")

    def _run_driver() -> int:
        proc = subprocess.Popen(
            [sys.executable, str(driver)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            print("  " + line.rstrip())
        return proc.wait()

    rc = await asyncio.to_thread(_run_driver)
    until = datetime.now(timezone.utc)
    return await _snapshot(
        "rag_courseware", since, until, provider=provider,
        extra={"driver": str(driver), "return_code": rc},
    )


async def scenario_parallel_research(provider: str) -> Path:
    """Sub-agent fanout scenario — placeholder.

    Needs a chat turn that prompts the coordinator to spawn >=3 researcher
    sub-agents in parallel. Deferred: wire a fixed prompt once the real
    LLM is available and the coordinator agent is known to cooperate.
    """
    now = datetime.now(timezone.utc)
    return await _snapshot(
        "parallel_research", now, now, provider=provider,
        extra={"status": "not_implemented", "todo": "fixed fanout prompt"},
    )


SCENARIOS = {
    "blog_with_review": scenario_blog_with_review,
    "long_chat": scenario_long_chat,
    "rag_courseware": scenario_rag_courseware,
    "parallel_research": scenario_parallel_research,
}


# ── CLI ────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="mas-pipeline benchmark harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_collect = sub.add_parser(
        "collect", help="snapshot the last N minutes of telemetry as-is"
    )
    p_collect.add_argument("--minutes", type=int, default=60)
    p_collect.add_argument("--provider", default="any")

    p_run = sub.add_parser("run", help="run one scenario")
    p_run.add_argument(
        "--scenario", required=True, choices=sorted(SCENARIOS.keys())
    )
    p_run.add_argument("--provider", default="mock", choices=["mock", "real"])

    p_all = sub.add_parser("all", help="run every scenario in order")
    p_all.add_argument("--provider", default="mock", choices=["mock", "real"])

    return p


async def _amain(args: argparse.Namespace) -> int:
    if args.cmd == "collect":
        await scenario_collect(args.minutes, provider=args.provider)
        return 0
    if args.cmd == "run":
        await SCENARIOS[args.scenario](args.provider)
        return 0
    if args.cmd == "all":
        for name, fn in SCENARIOS.items():
            print(f"\n=== scenario: {name} ===")
            try:
                await fn(args.provider)
            except Exception as exc:
                print(f"[bench] {name} failed: {exc!r}")
        return 0
    return 1


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
