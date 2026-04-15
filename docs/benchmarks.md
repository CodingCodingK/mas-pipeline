# mas-pipeline Benchmarks

Generated from 4 snapshot(s).


## collect — any

- Source: `.plan\benchmarks\20260414_075316_collect_any.json`
- Window: `2026-04-13T07:53:16.117167+00:00` → `2026-04-14T07:53:16.117167+00:00`



### LLM latency
> LLM 首 token + 总耗时延迟分布。回答面试官'长尾抖动'问题的原始数据。

| metric | value |
|---|---|
| count         | 36 |
| mean_ms       | 5519.4 |
| p50_ms        | 4200.5 |
| p95_ms        | 14470.2 |
| p99_ms        | 49487.6 |

### Token cost
> 每次调用的 token 消耗与 USD 成本，汇总到 run / scenario 层。是成本敏感度叙事的硬数据。

| metric | value |
|---|---|
| calls              | 36 |
| input_tokens       | 6441 |
| output_tokens      | 827 |
| cache_read_tokens  | 0 |
| cost_usd           | 0.000000 |
| missing_pricing    | 36 |

### Tool round-trip
> 各 built-in tool 的往返延迟与失败率，指出工具层瓶颈。

| tool | count | failures | p50_ms | p95_ms |
|---|---|---|---|---|
| spawn_agent | 2 | 0 | 24.0 | 33.0 |


### RAG latency
> search_docs 专项切片，衡量 RAG 检索占工具总时长的比例。

| metric | value |
|---|---|
| count                  | 0 |
| p50_ms                 | 0.0 |
| p95_ms                 | 0.0 |
| share_of_tool_ms       | 0.0% |

### Compact stats
> micro / auto / reactive 三档触发频次与压缩比，证明 compact 策略有效。

| trigger | count | mean_before | mean_after | mean_ratio |
|---|---|---|---|---|


### Sub-agent fanout
> coordinator spawns 的并发峰值 / 递归深度 / 平均扇出，展示多 agent 差异化能力。

| metric | value |
|---|---|
| max_concurrent        | 2 |
| total_spawns          | 2 |
| avg_fanout_per_parent | 2.0 |
| max_depth             | 1 |


## collect — mock

- Source: `.plan\benchmarks\20260414_080734_collect_mock.json`
- Window: `2026-04-14T07:52:33.982385+00:00` → `2026-04-14T08:07:33.982385+00:00`



### LLM latency
> LLM 首 token + 总耗时延迟分布。回答面试官'长尾抖动'问题的原始数据。

| metric | value |
|---|---|
| count         | 20 |
| mean_ms       | 11.4 |
| p50_ms        | 8.0 |
| p95_ms        | 24.6 |
| p99_ms        | 32.9 |

### Token cost
> 每次调用的 token 消耗与 USD 成本，汇总到 run / scenario 层。是成本敏感度叙事的硬数据。

| metric | value |
|---|---|
| calls              | 20 |
| input_tokens       | 200 |
| output_tokens      | 1000 |
| cache_read_tokens  | 0 |
| cost_usd           | 0.010500 |
| missing_pricing    | 0 |

### Tool round-trip
> 各 built-in tool 的往返延迟与失败率，指出工具层瓶颈。

| tool | count | failures | p50_ms | p95_ms |
|---|---|---|---|---|


### RAG latency
> search_docs 专项切片，衡量 RAG 检索占工具总时长的比例。

| metric | value |
|---|---|
| count                  | 0 |
| p50_ms                 | 0.0 |
| p95_ms                 | 0.0 |
| share_of_tool_ms       | 0.0% |

### Compact stats
> micro / auto / reactive 三档触发频次与压缩比，证明 compact 策略有效。

| trigger | count | mean_before | mean_after | mean_ratio |
|---|---|---|---|---|


### Sub-agent fanout
> coordinator spawns 的并发峰值 / 递归深度 / 平均扇出，展示多 agent 差异化能力。

| metric | value |
|---|---|
| max_concurrent        | 0 |
| total_spawns          | 0 |
| avg_fanout_per_parent | 0.0 |
| max_depth             | 0 |


## rag_courseware — real

- Source: `.plan\benchmarks\20260415_015817_rag_courseware_real.json`
- Window: `2026-04-15T01:54:24.199806+00:00` → `2026-04-15T01:58:17.508122+00:00`

- Extra: `{"driver": "scripts\\test_rag_e2e.py", "return_code": 0}`

### LLM latency
> LLM 首 token + 总耗时延迟分布。回答面试官'长尾抖动'问题的原始数据。

| metric | value |
|---|---|
| count         | 9 |
| mean_ms       | 38063.1 |
| p50_ms        | 47283.0 |
| p95_ms        | 80815.2 |
| p99_ms        | 84481.4 |

### Token cost
> 每次调用的 token 消耗与 USD 成本，汇总到 run / scenario 层。是成本敏感度叙事的硬数据。

| metric | value |
|---|---|
| calls              | 9 |
| input_tokens       | 57260 |
| output_tokens      | 15691 |
| cache_read_tokens  | 0 |
| cost_usd           | 0.000000 |
| missing_pricing    | 9 |

### Tool round-trip
> 各 built-in tool 的往返延迟与失败率，指出工具层瓶颈。

| tool | count | failures | p50_ms | p95_ms |
|---|---|---|---|---|
| search_docs | 6 | 0 | 182.5 | 247.0 |
| web_search | 6 | 0 | 1704.0 | 1921.5 |


### RAG latency
> search_docs 专项切片，衡量 RAG 检索占工具总时长的比例。

| metric | value |
|---|---|
| count                  | 6 |
| p50_ms                 | 182.5 |
| p95_ms                 | 247.0 |
| share_of_tool_ms       | 9.3% |

### Compact stats
> micro / auto / reactive 三档触发频次与压缩比，证明 compact 策略有效。

| trigger | count | mean_before | mean_after | mean_ratio |
|---|---|---|---|---|
| micro | 4 | 6512 | 3911 | 0.67 |


### Sub-agent fanout
> coordinator spawns 的并发峰值 / 递归深度 / 平均扇出，展示多 agent 差异化能力。

| metric | value |
|---|---|
| max_concurrent        | 0 |
| total_spawns          | 0 |
| avg_fanout_per_parent | 0.0 |
| max_depth             | 0 |


## rag_courseware — real

- Source: `.plan\benchmarks\20260415_020458_rag_courseware_real.json`
- Window: `2026-04-15T02:00:03.409993+00:00` → `2026-04-15T02:04:57.881725+00:00`

- Extra: `{"driver": "scripts\\test_rag_e2e.py", "return_code": 0}`

### LLM latency
> LLM 首 token + 总耗时延迟分布。回答面试官'长尾抖动'问题的原始数据。

| metric | value |
|---|---|
| count         | 5 |
| mean_ms       | 57967.0 |
| p50_ms        | 54436.0 |
| p95_ms        | 88012.2 |
| p99_ms        | 90468.8 |

### Token cost
> 每次调用的 token 消耗与 USD 成本，汇总到 run / scenario 层。是成本敏感度叙事的硬数据。

| metric | value |
|---|---|
| calls              | 5 |
| input_tokens       | 29139 |
| output_tokens      | 13005 |
| cache_read_tokens  | 0 |
| cost_usd           | 0.202898 |
| missing_pricing    | 0 |

### Tool round-trip
> 各 built-in tool 的往返延迟与失败率，指出工具层瓶颈。

| tool | count | failures | p50_ms | p95_ms |
|---|---|---|---|---|
| search_docs | 6 | 0 | 140.5 | 202.2 |


### RAG latency
> search_docs 专项切片，衡量 RAG 检索占工具总时长的比例。

| metric | value |
|---|---|
| count                  | 6 |
| p50_ms                 | 140.5 |
| p95_ms                 | 202.2 |
| share_of_tool_ms       | 100.0% |

### Compact stats
> micro / auto / reactive 三档触发频次与压缩比，证明 compact 策略有效。

| trigger | count | mean_before | mean_after | mean_ratio |
|---|---|---|---|---|
| micro | 1 | 2864 | 2577 | 0.90 |


### Sub-agent fanout
> coordinator spawns 的并发峰值 / 递归深度 / 平均扇出，展示多 agent 差异化能力。

| metric | value |
|---|---|
| max_concurrent        | 0 |
| total_spawns          | 0 |
| avg_fanout_per_parent | 0.0 |
| max_depth             | 0 |



## Resume-ready bullets

*(Anchored to `rag_courseware — real` run `.plan/benchmarks/20260415_020458_rag_courseware_real.json`, 2026-04-15.)*

- 设计并落地 mas-pipeline 多智能体内容流水线，单条 courseware 评审 run 耗时 ~292s、5 次 LLM 调用 + 6 次 RAG 检索即产出 4.8K 字审稿报告，端到端 p95 LLM 延迟 88 s、总成本 $0.20（gpt-5.4 via openai-compat 号池）。
- 通过 `SUM(cost_usd)` + `missing_pricing_calls` 二元统计让 pricing 缺失零容忍：修复 `_match_provider` 标签后 real-LLM 基线 `missing_pricing_calls=0`，cost_usd 从 $0.000 回归 $0.2029。
- 自建六维 bench harness（llm_latency / token_cost / tool_rtt / rag_latency / compact_stats / subagent_fanout），snapshot 落盘 + Markdown/HTML 双渲染；同一口径在 Observability Aggregate 页面复用，cost null 语义一致（skip-not-coerce）。
- RAG 检索中位延迟 140 ms、p95 202 ms，6/6 成功，占 scenario 全量 tool 时间 100%（该场景只挂 search_docs 一种工具）。
- Compact 运行时触发 1 次 micro 压缩，压缩率 0.90（2864 → 2577 tokens），长会话下会进一步放大，留给后续 7.2 压测继续取数。