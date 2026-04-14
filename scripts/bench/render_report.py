"""Render benchmark snapshots into markdown + HTML report.

Reads one or more JSON files produced by ``scripts/bench/run_bench.py``
and renders a two-surface report:

- ``docs/benchmarks.md``   — plain markdown, numbers only (easy to diff)
- ``docs/benchmarks.html`` — self-contained HTML with chart.js bar/line charts

Later the Phase 8.7 Observability tab will reuse the same SQL queries
(``src/bench/queries.py``) so the numbers shown on the web UI stay aligned
with what this report prints.

Usage
-----
    # render every json in .plan/benchmarks/
    python scripts/bench/render_report.py

    # render a specific file
    python scripts/bench/render_report.py --input .plan/benchmarks/xxx.json

    # render a glob
    python scripts/bench/render_report.py --input ".plan/benchmarks/*_mock.json"
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any

from jinja2 import Template

DEFAULT_INPUT_GLOB = ".plan/benchmarks/*.json"
DEFAULT_MD_OUT = Path("docs/benchmarks.md")
DEFAULT_HTML_OUT = Path("docs/benchmarks.html")


# ── Data loading ───────────────────────────────────────────────────


def _load_snapshots(patterns: list[str]) -> list[dict[str, Any]]:
    files: list[Path] = []
    for pat in patterns:
        for hit in sorted(glob.glob(pat)):
            files.append(Path(hit))
    snapshots: list[dict[str, Any]] = []
    for p in files:
        try:
            raw = p.read_text(encoding="utf-8")
            data = json.loads(raw)
            data["_source"] = str(p)
            snapshots.append(data)
        except Exception as exc:
            print(f"[render_report] skipping {p}: {exc!r}", file=sys.stderr)
    return snapshots


# ── Narrative strings (the "this number is for X" column) ──────────


METRIC_NARRATIVE = {
    "llm_latency": (
        "LLM 首 token + 总耗时延迟分布。回答面试官'长尾抖动'问题的原始数据。"
    ),
    "token_cost": (
        "每次调用的 token 消耗与 USD 成本，汇总到 run / scenario 层。"
        "是成本敏感度叙事的硬数据。"
    ),
    "tool_rtt": (
        "各 built-in tool 的往返延迟与失败率，指出工具层瓶颈。"
    ),
    "rag_latency": (
        "search_docs 专项切片，衡量 RAG 检索占工具总时长的比例。"
    ),
    "compact_stats": (
        "micro / auto / reactive 三档触发频次与压缩比，证明 compact 策略有效。"
    ),
    "subagent_fanout": (
        "coordinator spawns 的并发峰值 / 递归深度 / 平均扇出，展示多 agent 差异化能力。"
    ),
}


# ── Markdown template ──────────────────────────────────────────────


MD_TEMPLATE = Template(
    """# mas-pipeline Benchmarks

Generated from {{ snapshots|length }} snapshot(s).

{% for snap in snapshots %}
## {{ snap.scenario }} — {{ snap.provider }}

- Source: `{{ snap._source }}`
- Window: `{{ snap.since }}` → `{{ snap.until }}`
{% if snap.run_id %}- run_id: `{{ snap.run_id }}`{% endif %}
{% if snap.extra %}- Extra: `{{ snap.extra | tojson }}`{% endif %}

### LLM latency
> {{ narrative.llm_latency }}

| metric | value |
|---|---|
| count         | {{ snap.dimensions.llm_latency.count }} |
| mean_ms       | {{ "%.1f"|format(snap.dimensions.llm_latency.mean_ms) }} |
| p50_ms        | {{ "%.1f"|format(snap.dimensions.llm_latency.p50_ms) }} |
| p95_ms        | {{ "%.1f"|format(snap.dimensions.llm_latency.p95_ms) }} |
| p99_ms        | {{ "%.1f"|format(snap.dimensions.llm_latency.p99_ms) }} |

### Token cost
> {{ narrative.token_cost }}

| metric | value |
|---|---|
| calls              | {{ snap.dimensions.token_cost.calls }} |
| input_tokens       | {{ snap.dimensions.token_cost.input_tokens }} |
| output_tokens      | {{ snap.dimensions.token_cost.output_tokens }} |
| cache_read_tokens  | {{ snap.dimensions.token_cost.cache_read_tokens }} |
| cost_usd           | {{ "%.6f"|format(snap.dimensions.token_cost.cost_usd) }} |
| missing_pricing    | {{ snap.dimensions.token_cost.missing_pricing_calls }} |

### Tool round-trip
> {{ narrative.tool_rtt }}

| tool | count | failures | p50_ms | p95_ms |
|---|---|---|---|---|
{% for tool, info in snap.dimensions.tool_rtt.by_tool.items() -%}
| {{ tool }} | {{ info.count }} | {{ info.failures }} | {{ "%.1f"|format(info.p50_ms) }} | {{ "%.1f"|format(info.p95_ms) }} |
{% endfor %}

### RAG latency
> {{ narrative.rag_latency }}

| metric | value |
|---|---|
| count                  | {{ snap.dimensions.rag_latency.count }} |
| p50_ms                 | {{ "%.1f"|format(snap.dimensions.rag_latency.p50_ms) }} |
| p95_ms                 | {{ "%.1f"|format(snap.dimensions.rag_latency.p95_ms) }} |
| share_of_tool_ms       | {{ "%.1f%%"|format(snap.dimensions.rag_latency.share_of_tool_ms * 100) }} |

### Compact stats
> {{ narrative.compact_stats }}

| trigger | count | mean_before | mean_after | mean_ratio |
|---|---|---|---|---|
{% for trig, info in snap.dimensions.compact_stats.by_trigger.items() -%}
| {{ trig }} | {{ info.count }} | {{ "%.0f"|format(info.mean_before) }} | {{ "%.0f"|format(info.mean_after) }} | {{ "%.2f"|format(info.mean_ratio) }} |
{% endfor %}

### Sub-agent fanout
> {{ narrative.subagent_fanout }}

| metric | value |
|---|---|
| max_concurrent        | {{ snap.dimensions.subagent_fanout.max_concurrent }} |
| total_spawns          | {{ snap.dimensions.subagent_fanout.total_spawns }} |
| avg_fanout_per_parent | {{ snap.dimensions.subagent_fanout.avg_fanout_per_parent }} |
| max_depth             | {{ snap.dimensions.subagent_fanout.max_depth }} |

{% endfor %}

## Resume-ready bullets

*(Fill in after real-LLM baseline — placeholders below come from the raw snapshots above.)*

- **LLM 延迟 p95** — {{ "%.0f"|format(summary.llm_p95) }} ms
- **单次 run 平均成本** — ${{ "%.4f"|format(summary.avg_cost) }} USD
- **工具失败率** — {{ "%.1f%%"|format(summary.tool_failure_rate * 100) }}
- **RAG 占工具时长** — {{ "%.0f%%"|format(summary.rag_share * 100) }}
- **Compact 平均压缩比** — {{ "%.2f"|format(summary.compact_ratio) }}
- **sub-agent 并发峰值** — {{ summary.peak_concurrent }}
"""
)


# ── HTML template (self-contained, chart.js via CDN) ───────────────


HTML_TEMPLATE = Template(
    """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<title>mas-pipeline benchmarks</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  h1 { border-bottom: 2px solid #333; padding-bottom: .3rem; }
  h2 { margin-top: 2.5rem; border-bottom: 1px solid #ddd; padding-bottom: .2rem; }
  h3 { margin-top: 1.5rem; color: #555; }
  .narrative { color: #666; font-style: italic; margin: .3rem 0 1rem; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #ccc; padding: .35rem .6rem; text-align: left; }
  th { background: #f4f4f4; }
  canvas { max-width: 100%; }
  .card-row { display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0; }
  .card { flex: 1 1 180px; border: 1px solid #ccc; border-radius: 6px;
          padding: .8rem 1rem; background: #fafafa; }
  .card .label { font-size: .85rem; color: #777; }
  .card .value { font-size: 1.4rem; font-weight: 600; margin-top: .2rem; }
  code { background: #f4f4f4; padding: 0 .3rem; border-radius: 3px; }
</style>
</head>
<body>
<h1>mas-pipeline benchmarks</h1>
<p>Generated from {{ snapshots|length }} snapshot(s). Numbers come from the
same SQL queries as the future Observability tab.</p>

<div class="card-row">
  <div class="card"><div class="label">LLM p95 (ms)</div>
    <div class="value">{{ "%.0f"|format(summary.llm_p95) }}</div></div>
  <div class="card"><div class="label">Avg cost / run (USD)</div>
    <div class="value">{{ "%.4f"|format(summary.avg_cost) }}</div></div>
  <div class="card"><div class="label">Tool failure rate</div>
    <div class="value">{{ "%.1f%%"|format(summary.tool_failure_rate * 100) }}</div></div>
  <div class="card"><div class="label">RAG share of tool-ms</div>
    <div class="value">{{ "%.0f%%"|format(summary.rag_share * 100) }}</div></div>
  <div class="card"><div class="label">Compact ratio</div>
    <div class="value">{{ "%.2f"|format(summary.compact_ratio) }}</div></div>
  <div class="card"><div class="label">Peak sub-agent concurrency</div>
    <div class="value">{{ summary.peak_concurrent }}</div></div>
</div>

{% for snap in snapshots %}
<h2>{{ snap.scenario }} — {{ snap.provider }}</h2>
<p class="narrative">Source: <code>{{ snap._source }}</code> · Window: <code>{{ snap.since }}</code> → <code>{{ snap.until }}</code></p>

<h3>LLM latency (ms)</h3>
<p class="narrative">{{ narrative.llm_latency }}</p>
<canvas id="chart_llm_{{ loop.index }}"></canvas>

<h3>Token cost by model</h3>
<p class="narrative">{{ narrative.token_cost }}</p>
<canvas id="chart_cost_{{ loop.index }}"></canvas>

<h3>Tool round-trip</h3>
<p class="narrative">{{ narrative.tool_rtt }}</p>
<canvas id="chart_tool_{{ loop.index }}"></canvas>

<h3>Compact stats</h3>
<p class="narrative">{{ narrative.compact_stats }}</p>
<canvas id="chart_compact_{{ loop.index }}"></canvas>

<h3>Sub-agent fanout</h3>
<p class="narrative">{{ narrative.subagent_fanout }}</p>
<table>
  <tr><th>max_concurrent</th><td>{{ snap.dimensions.subagent_fanout.max_concurrent }}</td></tr>
  <tr><th>total_spawns</th><td>{{ snap.dimensions.subagent_fanout.total_spawns }}</td></tr>
  <tr><th>avg_fanout_per_parent</th><td>{{ snap.dimensions.subagent_fanout.avg_fanout_per_parent }}</td></tr>
  <tr><th>max_depth</th><td>{{ snap.dimensions.subagent_fanout.max_depth }}</td></tr>
</table>
{% endfor %}

<script>
const SNAPSHOTS = {{ snapshots_json }};
SNAPSHOTS.forEach((snap, i) => {
  const idx = i + 1;
  const llm = snap.dimensions.llm_latency;
  new Chart(document.getElementById(`chart_llm_${idx}`), {
    type: "bar",
    data: {
      labels: ["p50", "p95", "p99", "mean"],
      datasets: [{
        label: "latency (ms)",
        data: [llm.p50_ms, llm.p95_ms, llm.p99_ms, llm.mean_ms],
        backgroundColor: "#4a90e2",
      }],
    },
  });
  const cost = snap.dimensions.token_cost.by_model;
  new Chart(document.getElementById(`chart_cost_${idx}`), {
    type: "bar",
    data: {
      labels: Object.keys(cost),
      datasets: [{
        label: "cost_usd",
        data: Object.values(cost).map(m => m.cost_usd),
        backgroundColor: "#f5a623",
      }],
    },
  });
  const tools = snap.dimensions.tool_rtt.by_tool;
  new Chart(document.getElementById(`chart_tool_${idx}`), {
    type: "bar",
    data: {
      labels: Object.keys(tools),
      datasets: [
        { label: "p50_ms", data: Object.values(tools).map(t => t.p50_ms),
          backgroundColor: "#7ed321" },
        { label: "p95_ms", data: Object.values(tools).map(t => t.p95_ms),
          backgroundColor: "#bd10e0" },
      ],
    },
  });
  const cmp = snap.dimensions.compact_stats.by_trigger;
  new Chart(document.getElementById(`chart_compact_${idx}`), {
    type: "bar",
    data: {
      labels: Object.keys(cmp),
      datasets: [
        { label: "mean_before", data: Object.values(cmp).map(c => c.mean_before),
          backgroundColor: "#50e3c2" },
        { label: "mean_after", data: Object.values(cmp).map(c => c.mean_after),
          backgroundColor: "#9013fe" },
      ],
    },
  });
});
</script>
</body>
</html>
"""
)


# ── Aggregation for the summary card row ───────────────────────────


def _summarise(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick representative numbers for the top-level card row.

    Current heuristic: use the max across all snapshots for each metric.
    For single-snapshot reports this collapses to the single value.
    """
    def _max(path: list[str], default: float = 0.0) -> float:
        best = default
        for snap in snapshots:
            cur: Any = snap.get("dimensions", {})
            for key in path:
                cur = cur.get(key, {}) if isinstance(cur, dict) else 0
            if isinstance(cur, (int, float)) and cur > best:
                best = float(cur)
        return best

    def _avg(path: list[str]) -> float:
        vals: list[float] = []
        for snap in snapshots:
            cur: Any = snap.get("dimensions", {})
            for key in path:
                cur = cur.get(key, {}) if isinstance(cur, dict) else 0
            if isinstance(cur, (int, float)):
                vals.append(float(cur))
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "llm_p95": _max(["llm_latency", "p95_ms"]),
        "avg_cost": _avg(["token_cost", "cost_usd"]),
        "tool_failure_rate": _avg(["tool_rtt", "failure_rate"]),
        "rag_share": _avg(["rag_latency", "share_of_tool_ms"]),
        "compact_ratio": _avg(["compact_stats", "by_trigger", "auto", "mean_ratio"]),
        "peak_concurrent": int(_max(["subagent_fanout", "max_concurrent"])),
    }


# ── CLI ────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Render bench snapshots -> md + html")
    p.add_argument(
        "--input",
        action="append",
        default=None,
        help="snapshot file or glob (repeatable). Defaults to .plan/benchmarks/*.json",
    )
    p.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    p.add_argument("--html-out", type=Path, default=DEFAULT_HTML_OUT)
    return p


def main() -> int:
    args = _build_parser().parse_args()
    patterns = args.input or [DEFAULT_INPUT_GLOB]
    snapshots = _load_snapshots(patterns)
    if not snapshots:
        print(
            "[render_report] no snapshots matched; run scripts/bench/run_bench.py first.",
            file=sys.stderr,
        )
        return 1

    summary = _summarise(snapshots)

    md = MD_TEMPLATE.render(
        snapshots=snapshots,
        narrative=METRIC_NARRATIVE,
        summary=summary,
    )
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.write_text(md, encoding="utf-8")
    print(f"[render_report] wrote {args.md_out}")

    html = HTML_TEMPLATE.render(
        snapshots=snapshots,
        narrative=METRIC_NARRATIVE,
        summary=summary,
        snapshots_json=json.dumps(snapshots, default=str, ensure_ascii=False),
    )
    args.html_out.parent.mkdir(parents=True, exist_ok=True)
    args.html_out.write_text(html, encoding="utf-8")
    print(f"[render_report] wrote {args.html_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
