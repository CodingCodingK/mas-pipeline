## MODIFIED Requirements

### Requirement: Cost calculation from snapshotted pricing table
`TelemetryCollector` SHALL load a `PricingTable` from `config/pricing.yaml` at construction time. The table SHALL map `(provider, model)` to `{input_usd_per_1k_tokens, output_usd_per_1k_tokens, cache_read_discount_factor}`.

For each `llm_call` event, cost SHALL be calculated as:
```
cost_usd = (
    (input_tokens - cache_read_tokens) * input_usd_per_1k / 1000
    + cache_read_tokens * input_usd_per_1k * cache_read_discount_factor / 1000
    + output_tokens * output_usd_per_1k / 1000
)
```

If `(provider, model)` is not in the pricing table, `cost_usd` SHALL be set to `null` and a WARNING SHALL be logged once per unseen `(provider, model)` pair per collector lifetime.

`config/pricing.yaml` SHALL be a plain, human-editable yaml file with a documented schema (one top-level `models:` key; each entry keyed by `{provider}/{model}` with the three numeric fields). Adding a new model SHALL require only a yaml edit — no code change.

The collector SHALL expose a `reload_pricing()` method that atomically swaps in a fresh `PricingTable` read from `pricing_table_path`. A POST `/api/admin/telemetry/reload-pricing` endpoint SHALL invoke this method so operators can update prices without restarting the server. Existing `cost_usd` values in `telemetry_events` are NEVER retroactively recomputed — only new events use the reloaded prices.

**Provider and model label normalization.** The `provider` and `model` strings used as keys into the pricing table SHALL match the strings used by the LLM router and adapter layer when emitting `llm_call` events. When the router or an adapter uses an internal alias (for example `"openai_compat"` for a proxied OpenAI-compatible endpoint) that alias SHALL either (a) be present as a distinct key in `config/pricing.yaml`, or (b) be normalized to the canonical upstream provider string (e.g., `"openai"`) at emit time — whichever approach is chosen, the emitted `llm_call` event's `payload.provider` and `payload.model` SHALL resolve to a present key in the pricing table for all models that are actually invoked in production.

The responsibility for preventing label mismatches rests on the emit side, not on the query side. Aggregation queries SHALL NOT silently coerce `null` cost values to zero; they SHALL preserve `null` through `SUM`/`AVG` operations (SQL default behavior) so that a missing price is distinguishable from a zero cost.

#### Scenario: Cost computed for known model
- **WHEN** an `llm_call` event is emitted for `(provider='anthropic', model='claude-opus-4-6')` with 1000 input tokens and 500 output tokens, and the pricing table has entries for that model
- **THEN** `cost_usd` SHALL be populated per the formula

#### Scenario: Unknown model yields null cost
- **WHEN** an `llm_call` event is emitted for `(provider='foobar', model='bar-v1')` not in the pricing table
- **THEN** `cost_usd` SHALL be `null`
- **AND** a WARNING SHALL be logged the first time this pair is seen

#### Scenario: Cache-read discount applied
- **WHEN** an event has 1000 input_tokens with 800 cache_read_tokens, and `cache_read_discount_factor=0.1`
- **THEN** cost_usd SHALL reflect 200 full-price input tokens + 800 discounted input tokens + output at full price

#### Scenario: Pricing reload picks up new prices without restart
- **WHEN** `config/pricing.yaml` is edited to add a new model and `POST /api/admin/telemetry/reload-pricing` is called
- **THEN** subsequent `llm_call` events for that model SHALL have `cost_usd` populated per the new entry
- **AND** existing events in `telemetry_events` SHALL retain their original `cost_usd` values

#### Scenario: Proxied OpenAI-compatible model resolves to a pricing entry
- **GIVEN** the LLM router is configured to call a proxied OpenAI-compatible endpoint and emits `llm_call` events
- **WHEN** an `llm_call` event is emitted for a model that the proxy serves
- **THEN** the emitted `payload.provider` and `payload.model` SHALL together resolve to a present key in `config/pricing.yaml`
- **AND** `cost_usd` SHALL be non-null for a successful call

#### Scenario: Aggregation preserves null costs
- **GIVEN** a mix of `llm_call` events in the telemetry table, some with `cost_usd=0.012` and others with `cost_usd=null`
- **WHEN** `GET /api/telemetry/aggregate` computes a windowed cost sum
- **THEN** the sum SHALL treat `null` values as unknown (standard SQL `SUM` behavior) and SHALL NOT implicitly convert them to zero before summing
- **AND** a non-null sum SHALL only reflect events whose cost was computed
