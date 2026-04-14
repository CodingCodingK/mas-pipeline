"""Six-dimension benchmark queries against `telemetry_events`.

All six functions share the same signature:

    async def <dim>(
        session: AsyncSession,
        *,
        project_id: int | None = None,
        run_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> dict

Filtering rules:
- project_id=None means "all projects" (bench scenarios often run across
  scratch projects; the CLI aggregate may want to ignore project boundary).
- run_id, when set, pins the query to one pipeline/agent run.
- since/until, when set, bound `ts` inclusive/exclusive respectively.

Return shape is stable per dimension — documented at each function.
Consumers in CLI report renderer and REST observability handler must not
reach around these functions into raw SQL; add a new arg here instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── Shared helpers ──────────────────────────────────────────────────


def _where_clause(
    project_id: int | None,
    run_id: str | None,
    since: datetime | None,
    until: datetime | None,
    event_type: str | None = None,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if event_type is not None:
        clauses.append("event_type = :event_type")
        params["event_type"] = event_type
    if project_id is not None:
        clauses.append("project_id = :project_id")
        params["project_id"] = project_id
    if run_id is not None:
        clauses.append("run_id = :run_id")
        params["run_id"] = run_id
    if since is not None:
        clauses.append("ts >= :since")
        params["since"] = since
    if until is not None:
        clauses.append("ts < :until")
        params["until"] = until
    sql = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return sql, params


# ── 1. LLM latency distribution ─────────────────────────────────────


async def llm_latency(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Return LLM latency percentiles + per-provider/model breakdown.

    Shape::

        {
          "count": int,
          "mean_ms": float,
          "p50_ms": float, "p95_ms": float, "p99_ms": float,
          "by_provider": {provider: {count, mean_ms, p95_ms}},
          "by_model":    {model:    {count, mean_ms, p95_ms}},
        }
    """
    where, params = _where_clause(project_id, run_id, since, until, "llm_call")

    sql_overall = f"""
        SELECT
          COUNT(*)::int AS count,
          COALESCE(AVG((payload->>'latency_ms')::float), 0) AS mean_ms,
          COALESCE(
            percentile_cont(0.50) WITHIN GROUP (
              ORDER BY (payload->>'latency_ms')::float
            ), 0
          ) AS p50_ms,
          COALESCE(
            percentile_cont(0.95) WITHIN GROUP (
              ORDER BY (payload->>'latency_ms')::float
            ), 0
          ) AS p95_ms,
          COALESCE(
            percentile_cont(0.99) WITHIN GROUP (
              ORDER BY (payload->>'latency_ms')::float
            ), 0
          ) AS p99_ms
        FROM telemetry_events
        {where}
    """
    overall_row = (await session.execute(text(sql_overall), params)).mappings().one()

    sql_group = f"""
        SELECT
          payload->>'{{key}}' AS k,
          COUNT(*)::int AS count,
          COALESCE(AVG((payload->>'latency_ms')::float), 0) AS mean_ms,
          COALESCE(
            percentile_cont(0.95) WITHIN GROUP (
              ORDER BY (payload->>'latency_ms')::float
            ), 0
          ) AS p95_ms
        FROM telemetry_events
        {where}
        GROUP BY k
    """

    by_provider_rows = (
        await session.execute(
            text(sql_group.replace("{key}", "provider")), params
        )
    ).mappings().all()
    by_model_rows = (
        await session.execute(
            text(sql_group.replace("{key}", "model")), params
        )
    ).mappings().all()

    return {
        "count": int(overall_row["count"]),
        "mean_ms": float(overall_row["mean_ms"]),
        "p50_ms": float(overall_row["p50_ms"]),
        "p95_ms": float(overall_row["p95_ms"]),
        "p99_ms": float(overall_row["p99_ms"]),
        "by_provider": {
            (r["k"] or "unknown"): {
                "count": int(r["count"]),
                "mean_ms": float(r["mean_ms"]),
                "p95_ms": float(r["p95_ms"]),
            }
            for r in by_provider_rows
        },
        "by_model": {
            (r["k"] or "unknown"): {
                "count": int(r["count"]),
                "mean_ms": float(r["mean_ms"]),
                "p95_ms": float(r["p95_ms"]),
            }
            for r in by_model_rows
        },
    }


# ── 2. Token cost ───────────────────────────────────────────────────


async def token_cost(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Return token and ¥ totals per provider/model.

    Shape::

        {
          "calls": int,
          "input_tokens": int, "output_tokens": int, "cache_read_tokens": int,
          "cost_usd": float,
          "missing_pricing_calls": int,   # cost_usd IS NULL rows
          "by_model": {model: {calls, input_tokens, output_tokens, cost_usd}},
        }
    """
    where, params = _where_clause(project_id, run_id, since, until, "llm_call")

    sql_overall = f"""
        SELECT
          COUNT(*)::int AS calls,
          COALESCE(SUM((payload->>'input_tokens')::int), 0)::bigint AS input_tokens,
          COALESCE(SUM((payload->>'output_tokens')::int), 0)::bigint AS output_tokens,
          COALESCE(SUM((payload->>'cache_read_tokens')::int), 0)::bigint AS cache_read_tokens,
          COALESCE(SUM((payload->>'cost_usd')::float), 0)::float AS cost_usd,
          SUM(
            CASE WHEN payload->>'cost_usd' IS NULL THEN 1 ELSE 0 END
          )::int AS missing_pricing_calls
        FROM telemetry_events
        {where}
    """
    row = (await session.execute(text(sql_overall), params)).mappings().one()

    sql_group = f"""
        SELECT
          payload->>'model' AS model,
          COUNT(*)::int AS calls,
          COALESCE(SUM((payload->>'input_tokens')::int), 0)::bigint AS input_tokens,
          COALESCE(SUM((payload->>'output_tokens')::int), 0)::bigint AS output_tokens,
          COALESCE(SUM((payload->>'cost_usd')::float), 0)::float AS cost_usd
        FROM telemetry_events
        {where}
        GROUP BY model
    """
    group_rows = (await session.execute(text(sql_group), params)).mappings().all()

    return {
        "calls": int(row["calls"]),
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "cache_read_tokens": int(row["cache_read_tokens"]),
        "cost_usd": float(row["cost_usd"]),
        "missing_pricing_calls": int(row["missing_pricing_calls"]),
        "by_model": {
            (r["model"] or "unknown"): {
                "calls": int(r["calls"]),
                "input_tokens": int(r["input_tokens"]),
                "output_tokens": int(r["output_tokens"]),
                "cost_usd": float(r["cost_usd"]),
            }
            for r in group_rows
        },
    }


# ── 3. Tool call round-trip ─────────────────────────────────────────


async def tool_rtt(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Per-tool latency distribution and failure rate.

    Shape::

        {
          "count": int,
          "failure_rate": float,
          "by_tool": {
            tool_name: {count, failures, failure_rate,
                        mean_ms, p50_ms, p95_ms}
          }
        }
    """
    where, params = _where_clause(project_id, run_id, since, until, "tool_call")
    if tool_name is not None:
        where = where + " AND payload->>'tool_name' = :tool_name"
        params = {**params, "tool_name": tool_name}

    sql_overall = f"""
        SELECT
          COUNT(*)::int AS count,
          SUM(
            CASE WHEN (payload->>'success')::bool IS FALSE THEN 1 ELSE 0 END
          )::int AS failures
        FROM telemetry_events
        {where}
    """
    row = (await session.execute(text(sql_overall), params)).mappings().one()
    total = int(row["count"])
    failures = int(row["failures"] or 0)

    sql_group = f"""
        SELECT
          payload->>'tool_name' AS tool_name,
          COUNT(*)::int AS count,
          SUM(
            CASE WHEN (payload->>'success')::bool IS FALSE THEN 1 ELSE 0 END
          )::int AS failures,
          COALESCE(AVG((payload->>'duration_ms')::float), 0) AS mean_ms,
          COALESCE(
            percentile_cont(0.50) WITHIN GROUP (
              ORDER BY (payload->>'duration_ms')::float
            ), 0
          ) AS p50_ms,
          COALESCE(
            percentile_cont(0.95) WITHIN GROUP (
              ORDER BY (payload->>'duration_ms')::float
            ), 0
          ) AS p95_ms
        FROM telemetry_events
        {where}
        GROUP BY tool_name
        ORDER BY count DESC
    """
    group_rows = (await session.execute(text(sql_group), params)).mappings().all()

    by_tool: dict[str, Any] = {}
    for r in group_rows:
        t_count = int(r["count"])
        t_fail = int(r["failures"] or 0)
        by_tool[r["tool_name"] or "unknown"] = {
            "count": t_count,
            "failures": t_fail,
            "failure_rate": (t_fail / t_count) if t_count else 0.0,
            "mean_ms": float(r["mean_ms"]),
            "p50_ms": float(r["p50_ms"]),
            "p95_ms": float(r["p95_ms"]),
        }

    return {
        "count": total,
        "failure_rate": (failures / total) if total else 0.0,
        "by_tool": by_tool,
    }


# ── 4. RAG retrieval latency ────────────────────────────────────────


async def rag_latency(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Slice of tool_rtt for search_docs, plus "share of total tool time".

    Share is wall-clock share: sum(search_docs.duration_ms) / sum(all tool.duration_ms).
    Useful for the bullet "RAG 占 N% 的工具时长".
    """
    tool_slice = await tool_rtt(
        session,
        project_id=project_id,
        run_id=run_id,
        since=since,
        until=until,
        tool_name="search_docs",
    )

    all_tools = await tool_rtt(
        session,
        project_id=project_id,
        run_id=run_id,
        since=since,
        until=until,
    )
    all_sum_sql, all_params = _where_clause(
        project_id, run_id, since, until, "tool_call"
    )
    share_row = (
        await session.execute(
            text(
                f"""
                SELECT
                  COALESCE(SUM(
                    CASE WHEN payload->>'tool_name' = 'search_docs'
                         THEN (payload->>'duration_ms')::float ELSE 0 END
                  ), 0) AS rag_ms,
                  COALESCE(SUM((payload->>'duration_ms')::float), 0) AS all_ms
                FROM telemetry_events
                {all_sum_sql}
                """
            ),
            all_params,
        )
    ).mappings().one()

    rag_ms = float(share_row["rag_ms"])
    all_ms = float(share_row["all_ms"])

    info = tool_slice.get("by_tool", {}).get("search_docs", {
        "count": 0, "failures": 0, "failure_rate": 0.0,
        "mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0,
    })
    return {
        **info,
        "share_of_tool_ms": (rag_ms / all_ms) if all_ms > 0 else 0.0,
        "all_tools_total_count": all_tools["count"],
    }


# ── 5. Compact stats ────────────────────────────────────────────────


async def compact_stats(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Compact trigger counts + compression ratio per trigger.

    Shape::

        {
          "count": int,
          "by_trigger": {
            "auto"|"reactive"|"micro": {
              count, mean_before, mean_after, mean_ratio,
              mean_duration_ms
            }
          }
        }
    """
    where, params = _where_clause(project_id, run_id, since, until, "compact")

    sql_overall = f"SELECT COUNT(*)::int AS count FROM telemetry_events {where}"
    total_row = (await session.execute(text(sql_overall), params)).mappings().one()

    sql_group = f"""
        SELECT
          payload->>'trigger' AS trigger,
          COUNT(*)::int AS count,
          COALESCE(AVG((payload->>'before_tokens')::int), 0) AS mean_before,
          COALESCE(AVG((payload->>'after_tokens')::int), 0) AS mean_after,
          COALESCE(AVG((payload->>'ratio')::float), 0) AS mean_ratio,
          COALESCE(AVG((payload->>'duration_ms')::int), 0) AS mean_duration_ms
        FROM telemetry_events
        {where}
        GROUP BY trigger
    """
    rows = (await session.execute(text(sql_group), params)).mappings().all()

    return {
        "count": int(total_row["count"]),
        "by_trigger": {
            (r["trigger"] or "unknown"): {
                "count": int(r["count"]),
                "mean_before": float(r["mean_before"]),
                "mean_after": float(r["mean_after"]),
                "mean_ratio": float(r["mean_ratio"]),
                "mean_duration_ms": float(r["mean_duration_ms"]),
            }
            for r in rows
        },
    }


# ── 6. Sub-agent fanout ─────────────────────────────────────────────


async def subagent_fanout(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Sub-agent concurrency + depth + average fanout.

    Zero new instrumentation: reads `agent_turn` and `agent_spawn` events.

    - `max_concurrent` is a sweep-line over [started_at, ended_at] of each
      agent_turn row, yielding the peak simultaneous running count.
    - `total_spawns` and `avg_fanout_per_parent` come from agent_spawn group-by.
    - `max_depth` is a simple heuristic: distinct child_roles - 1 when chains
      exist; a proper recursive walk needs parent_turn_id linking, which we
      don't fully close yet. A sentinel `max_depth_note` explains the caveat.

    Shape::

        {
          "max_concurrent": int,
          "total_spawns": int,
          "avg_fanout_per_parent": float,
          "max_depth": int,
          "max_depth_note": str,
        }
    """
    # --- sweep-line for peak concurrency ---
    turn_where, turn_params = _where_clause(
        project_id, run_id, since, until, "agent_turn"
    )
    sql_intervals = f"""
        SELECT
          (payload->>'started_at')::timestamptz AS started_at,
          (payload->>'ended_at')::timestamptz AS ended_at
        FROM telemetry_events
        {turn_where}
    """
    rows = (await session.execute(text(sql_intervals), turn_params)).mappings().all()

    events: list[tuple[datetime, int]] = []
    for r in rows:
        if r["started_at"] is not None and r["ended_at"] is not None:
            events.append((r["started_at"], 1))
            events.append((r["ended_at"], -1))
    events.sort(key=lambda x: (x[0], -x[1]))  # starts before ends at same ts
    max_concurrent = 0
    running = 0
    for _, delta in events:
        running += delta
        if running > max_concurrent:
            max_concurrent = running

    # --- spawn group-by for fanout ---
    spawn_where, spawn_params = _where_clause(
        project_id, run_id, since, until, "agent_spawn"
    )
    sql_spawn = f"""
        SELECT
          payload->>'parent_role' AS parent_role,
          COUNT(*)::int AS spawns
        FROM telemetry_events
        {spawn_where}
        GROUP BY parent_role
    """
    spawn_rows = (await session.execute(text(sql_spawn), spawn_params)).mappings().all()

    total_spawns = sum(int(r["spawns"]) for r in spawn_rows)
    avg_fanout = (
        total_spawns / len(spawn_rows) if spawn_rows else 0.0
    )

    # --- depth heuristic ---
    # Count distinct child_role chains where the child_role also appears as a
    # parent_role in another spawn. Two-level: 1 if any child re-spawns.
    sql_depth = f"""
        SELECT COUNT(DISTINCT payload->>'child_role') AS nested
        FROM telemetry_events t1
        {spawn_where}
        AND EXISTS (
          SELECT 1 FROM telemetry_events t2
          WHERE t2.event_type = 'agent_spawn'
            AND t2.payload->>'parent_role' = t1.payload->>'child_role'
        )
    """
    nested_row = (
        await session.execute(text(sql_depth), spawn_params)
    ).mappings().one()
    nested = int(nested_row["nested"] or 0)
    max_depth = 2 if nested > 0 else (1 if total_spawns > 0 else 0)

    return {
        "max_concurrent": max_concurrent,
        "total_spawns": total_spawns,
        "avg_fanout_per_parent": round(avg_fanout, 2),
        "max_depth": max_depth,
        "max_depth_note": (
            "heuristic: 0/1/2 via spawn chain existence; full recursive "
            "depth not computed (requires parent_turn_id walk)."
        ),
    }


# ── Aggregate entry point ───────────────────────────────────────────


async def all_dimensions(
    session: AsyncSession,
    *,
    project_id: int | None = None,
    run_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """One-shot call returning all six dims under a single dict.

    Consumed by `scripts/bench/render_report.py` and the REST
    `/api/projects/{id}/observability/summary` handler (Phase 8.7).
    """
    common = dict(
        project_id=project_id,
        run_id=run_id,
        since=since,
        until=until,
    )
    return {
        "llm_latency": await llm_latency(session, **common),
        "token_cost": await token_cost(session, **common),
        "tool_rtt": await tool_rtt(session, **common),
        "rag_latency": await rag_latency(session, **common),
        "compact_stats": await compact_stats(session, **common),
        "subagent_fanout": await subagent_fanout(session, **common),
    }
