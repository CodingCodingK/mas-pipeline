"""Telemetry query layer: read-side aggregation over `telemetry_events`.

All functions run against the same async session factory used by the
collector. Tree reconstruction happens client-side in Python so the DB
schema stays simple.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import text

from src.db import get_session_factory


async def _fetch_run_events(run_id: str) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT id, ts, event_type, project_id, run_id, session_id, "
                "agent_role, payload FROM telemetry_events "
                "WHERE run_id = :run_id ORDER BY ts ASC, id ASC"
            ),
            {"run_id": run_id},
        )
        return [_row_to_dict(r) for r in result.mappings().all()]


async def _fetch_session_events(session_id: int) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT id, ts, event_type, project_id, run_id, session_id, "
                "agent_role, payload FROM telemetry_events "
                "WHERE session_id = :session_id ORDER BY ts ASC, id ASC"
            ),
            {"session_id": session_id},
        )
        return [_row_to_dict(r) for r in result.mappings().all()]


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    if isinstance(d.get("ts"), datetime):
        d["ts_iso"] = d["ts"].isoformat()
    return d


# ── Summary aggregations ──────────────────────────────────


def _summarise(events: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    total_input = 0
    total_output = 0
    total_cost = 0.0
    total_latency_ms = 0
    llm_calls = 0
    tool_calls = 0
    errors = 0
    start_ts: datetime | None = None
    end_ts: datetime | None = None

    for e in events:
        counts[e["event_type"]] += 1
        ts = e.get("ts")
        if isinstance(ts, datetime):
            if start_ts is None or ts < start_ts:
                start_ts = ts
            if end_ts is None or ts > end_ts:
                end_ts = ts
        p = e.get("payload") or {}
        if e["event_type"] == "llm_call":
            llm_calls += 1
            total_input += int(p.get("input_tokens") or 0)
            total_output += int(p.get("output_tokens") or 0)
            cost = p.get("cost_usd")
            if cost is not None:
                total_cost += float(cost)
            total_latency_ms += int(p.get("latency_ms") or 0)
        elif e["event_type"] == "tool_call":
            tool_calls += 1
        elif e["event_type"] == "error":
            errors += 1

    duration_ms: int | None = None
    if start_ts and end_ts:
        duration_ms = int((end_ts - start_ts).total_seconds() * 1000)

    return {
        "event_counts": dict(counts),
        "total_events": len(events),
        "llm_calls": llm_calls,
        "tool_calls": tool_calls,
        "errors": errors,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 6),
        "total_llm_latency_ms": total_latency_ms,
        "duration_ms": duration_ms,
        "started_at": start_ts.isoformat() if start_ts else None,
        "ended_at": end_ts.isoformat() if end_ts else None,
    }


async def get_run_summary(run_id: str) -> dict[str, Any]:
    events = await _fetch_run_events(run_id)
    if not events:
        raise KeyError(f"run_id={run_id!r} has no telemetry events")
    summary = _summarise(events)
    summary["run_id"] = run_id
    summary["project_id"] = events[0]["project_id"]
    return summary


async def get_session_summary(session_id: int) -> dict[str, Any]:
    events = await _fetch_session_events(session_id)
    if not events:
        raise KeyError(f"session_id={session_id} has no telemetry events")
    summary = _summarise(events)
    summary["session_id"] = session_id
    summary["project_id"] = events[0]["project_id"]
    return summary


# ── Timeline ──────────────────────────────────────────────


async def get_run_timeline(run_id: str) -> list[dict[str, Any]]:
    events = await _fetch_run_events(run_id)
    if not events:
        raise KeyError(f"run_id={run_id!r} has no telemetry events")
    return [_public_event(e) for e in events]


def _public_event(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": e["id"],
        "ts": e["ts"].isoformat() if isinstance(e.get("ts"), datetime) else None,
        "event_type": e["event_type"],
        "project_id": e["project_id"],
        "run_id": e.get("run_id"),
        "session_id": e.get("session_id"),
        "agent_role": e.get("agent_role"),
        "payload": e.get("payload") or {},
    }


# ── Tree reconstruction (A6 algorithm) ────────────────────


def _build_tree(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a hierarchical tree from a flat event list.

    Nodes:
      - agent_turn (by turn_id) — children = llm_calls, tool_calls, hook_events
        whose parent_turn_id matches, and child agent_turns whose
        spawned_by_spawn_id matches this turn's spawn_ids.
      - agent_spawn — associates parent_turn_id (parent) with spawn_id
        which child turn references via spawned_by_spawn_id.

    Output shape:
        {"roots": [turn_node, ...], "orphans": [...]}
    """
    turns_by_id: dict[str, dict[str, Any]] = {}
    spawns_by_id: dict[str, dict[str, Any]] = {}
    children_of_turn: dict[str, list[dict[str, Any]]] = defaultdict(list)
    spawn_to_parent_turn: dict[str, str] = {}

    # First pass: index turns and spawns
    for e in events:
        et = e["event_type"]
        p = e.get("payload") or {}
        if et == "agent_turn":
            turn_id = p.get("turn_id")
            if turn_id:
                turns_by_id[turn_id] = {
                    "turn_id": turn_id,
                    "agent_role": p.get("agent_role"),
                    "turn_index": p.get("turn_index"),
                    "started_at": p.get("started_at"),
                    "ended_at": p.get("ended_at"),
                    "duration_ms": p.get("duration_ms"),
                    "stop_reason": p.get("stop_reason"),
                    "input_preview": p.get("input_preview"),
                    "output_preview": p.get("output_preview"),
                    "spawned_by_spawn_id": p.get("spawned_by_spawn_id"),
                    "children": [],
                    "child_turns": [],
                }
        elif et == "agent_spawn":
            sid = p.get("spawn_id")
            if sid:
                spawns_by_id[sid] = {
                    "spawn_id": sid,
                    "parent_role": p.get("parent_role"),
                    "child_role": p.get("child_role"),
                    "task_preview": p.get("task_preview"),
                    "parent_turn_id": p.get("parent_turn_id"),
                }
                if p.get("parent_turn_id"):
                    spawn_to_parent_turn[sid] = p["parent_turn_id"]

    # Second pass: attach llm/tool/hook to parent turn
    for e in events:
        et = e["event_type"]
        p = e.get("payload") or {}
        parent = p.get("parent_turn_id")
        if et in ("llm_call", "tool_call", "hook_event", "error") and parent:
            children_of_turn[parent].append(_public_event(e))

    # Third pass: link child turns to parent turns via spawn_id
    roots: list[dict[str, Any]] = []
    orphans: list[dict[str, Any]] = []
    for turn_id, node in turns_by_id.items():
        node["children"] = children_of_turn.get(turn_id, [])
        spawned_by = node.get("spawned_by_spawn_id")
        if spawned_by and spawned_by in spawn_to_parent_turn:
            parent_turn_id = spawn_to_parent_turn[spawned_by]
            parent_node = turns_by_id.get(parent_turn_id)
            if parent_node is not None:
                parent_node["child_turns"].append(node)
                continue
            orphans.append(node)
        else:
            roots.append(node)

    return {
        "roots": roots,
        "orphans": orphans,
        "spawns": list(spawns_by_id.values()),
    }


async def get_run_tree(run_id: str) -> dict[str, Any]:
    events = await _fetch_run_events(run_id)
    if not events:
        raise KeyError(f"run_id={run_id!r} has no telemetry events")
    tree = _build_tree(events)
    tree["run_id"] = run_id
    return tree


async def get_session_tree(session_id: int) -> dict[str, Any]:
    events = await _fetch_session_events(session_id)
    if not events:
        raise KeyError(f"session_id={session_id} has no telemetry events")
    tree = _build_tree(events)
    tree["session_id"] = session_id
    return tree


# ── Per-agent rollup ──────────────────────────────────────


async def get_run_agents(run_id: str) -> list[dict[str, Any]]:
    events = await _fetch_run_events(run_id)
    if not events:
        raise KeyError(f"run_id={run_id!r} has no telemetry events")

    by_role: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "agent_role": None,
            "turn_count": 0,
            "llm_calls": 0,
            "tool_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "errors": 0,
        }
    )

    # Index turn_id -> agent_role for linking llm/tool events.
    turn_role: dict[str, str] = {}
    for e in events:
        if e["event_type"] == "agent_turn":
            p = e.get("payload") or {}
            tid = p.get("turn_id")
            role = p.get("agent_role") or "unknown"
            if tid:
                turn_role[tid] = role

    for e in events:
        et = e["event_type"]
        p = e.get("payload") or {}
        if et == "agent_turn":
            role = p.get("agent_role") or "unknown"
            agg = by_role[role]
            agg["agent_role"] = role
            agg["turn_count"] += 1
        elif et == "llm_call":
            role = turn_role.get(p.get("parent_turn_id"), "unknown")
            agg = by_role[role]
            agg["agent_role"] = role
            agg["llm_calls"] += 1
            agg["input_tokens"] += int(p.get("input_tokens") or 0)
            agg["output_tokens"] += int(p.get("output_tokens") or 0)
            if p.get("cost_usd") is not None:
                agg["cost_usd"] += float(p["cost_usd"])
        elif et == "tool_call":
            role = turn_role.get(p.get("parent_turn_id"), "unknown")
            agg = by_role[role]
            agg["agent_role"] = role
            agg["tool_calls"] += 1
        elif et == "error":
            role = turn_role.get(p.get("parent_turn_id"), "unknown")
            agg = by_role[role]
            agg["agent_role"] = role
            agg["errors"] += 1

    result = []
    for role, agg in by_role.items():
        agg["agent_role"] = role
        agg["cost_usd"] = round(agg["cost_usd"], 6)
        result.append(agg)
    return result


async def get_run_errors(run_id: str) -> list[dict[str, Any]]:
    events = await _fetch_run_events(run_id)
    return [_public_event(e) for e in events if e["event_type"] == "error"]


# ── Project-scoped aggregations ───────────────────────────


async def get_project_cost(
    project_id: int,
    from_: datetime | None = None,
    to_: datetime | None = None,
    group_by: str = "day",
    pipeline: str | None = None,
) -> list[dict[str, Any]]:
    """Roll up cost/tokens/latency for a project.

    group_by: "day" | "run" | "pipeline"
    """
    if group_by not in ("day", "run", "pipeline"):
        raise ValueError(f"invalid group_by: {group_by!r}")

    factory = get_session_factory()

    # Fetch llm_call + pipeline events in the window; group client-side so
    # the SQL stays simple and we can filter by pipeline cheaply.
    clauses = ["project_id = :project_id", "event_type IN ('llm_call','pipeline_event')"]
    params: dict[str, Any] = {"project_id": project_id}
    if from_ is not None:
        clauses.append("ts >= :from_ts")
        params["from_ts"] = from_
    if to_ is not None:
        clauses.append("ts <= :to_ts")
        params["to_ts"] = to_

    sql = (
        "SELECT ts, event_type, run_id, payload FROM telemetry_events "
        f"WHERE {' AND '.join(clauses)} ORDER BY ts ASC"
    )
    async with factory() as session:
        result = await session.execute(text(sql), params)
        rows = [dict(r) for r in result.mappings().all()]

    # Build run_id → pipeline_name map (from pipeline_start events)
    run_pipeline: dict[str, str] = {}
    for r in rows:
        if r["event_type"] == "pipeline_event":
            p = r.get("payload") or {}
            if p.get("pipeline_event_type") == "pipeline_start" and r.get("run_id"):
                run_pipeline[r["run_id"]] = p.get("pipeline_name") or ""

    def _key(row: dict[str, Any]) -> str | None:
        if group_by == "day":
            ts = row["ts"]
            return ts.strftime("%Y-%m-%d") if isinstance(ts, datetime) else None
        if group_by == "run":
            return row.get("run_id")
        if group_by == "pipeline":
            return run_pipeline.get(row.get("run_id") or "", "unknown")
        return None

    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "key": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "llm_calls": 0,
            "total_latency_ms": 0,
        }
    )

    for r in rows:
        if r["event_type"] != "llm_call":
            continue
        if pipeline is not None:
            if run_pipeline.get(r.get("run_id") or "") != pipeline:
                continue
        key = _key(r)
        if key is None:
            continue
        p = r.get("payload") or {}
        b = buckets[key]
        b["key"] = key
        b["llm_calls"] += 1
        b["input_tokens"] += int(p.get("input_tokens") or 0)
        b["output_tokens"] += int(p.get("output_tokens") or 0)
        if p.get("cost_usd") is not None:
            b["cost_usd"] += float(p["cost_usd"])
        b["total_latency_ms"] += int(p.get("latency_ms") or 0)

    out = []
    for b in buckets.values():
        b["cost_usd"] = round(b["cost_usd"], 6)
        out.append(b)
    out.sort(key=lambda x: str(x["key"]))
    return out


async def get_project_trends(
    project_id: int,
    from_: datetime | None = None,
    to_: datetime | None = None,
) -> dict[str, Any]:
    """Per-day averages: llm_latency_ms, tokens, cost."""
    daily = await get_project_cost(
        project_id=project_id, from_=from_, to_=to_, group_by="day"
    )
    series_latency: list[dict[str, Any]] = []
    series_tokens: list[dict[str, Any]] = []
    series_cost: list[dict[str, Any]] = []
    for b in daily:
        calls = max(b["llm_calls"], 1)
        series_latency.append({
            "day": b["key"],
            "avg_latency_ms": int(b["total_latency_ms"] / calls),
        })
        series_tokens.append({
            "day": b["key"],
            "input_tokens": b["input_tokens"],
            "output_tokens": b["output_tokens"],
        })
        series_cost.append({"day": b["key"], "cost_usd": b["cost_usd"]})

    return {
        "project_id": project_id,
        "latency": series_latency,
        "tokens": series_tokens,
        "cost": series_cost,
    }
