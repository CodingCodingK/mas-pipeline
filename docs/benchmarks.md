# mas-pipeline Benchmarks

Generated from 2 snapshot(s).


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



## Resume-ready bullets

*(Fill in after real-LLM baseline — placeholders below come from the raw snapshots above.)*

- **LLM 延迟 p95** — 14470 ms
- **单次 run 平均成本** — $0.0052 USD
- **工具失败率** — 0.0%
- **RAG 占工具时长** — 0%
- **Compact 平均压缩比** — 0.00
- **sub-agent 并发峰值** — 2