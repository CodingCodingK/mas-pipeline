"""Pricing table for LLM call cost calculation.

Schema of config/pricing.yaml:

    models:
      "{provider}/{model_name}":
        input_usd_per_1k_tokens: float
        output_usd_per_1k_tokens: float
        cache_read_discount_factor: float  # 0..1; fraction of input price
                                            # charged for cache-read tokens

To add a new model: append a new entry under `models:` and call
`collector.reload_pricing()` (or hit `POST /api/admin/telemetry/reload-pricing`).
Missing models cause cost_usd=null with a one-time WARNING per unseen pair.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ModelPricing:
    input_usd_per_1k_tokens: float
    output_usd_per_1k_tokens: float
    cache_read_discount_factor: float = 0.1


@dataclass
class PricingTable:
    models: dict[str, ModelPricing] = field(default_factory=dict)
    # Deduplicates the "unknown model" WARNING per (provider, model) pair.
    _warned: set[tuple[str, str]] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self, provider: str, model: str) -> ModelPricing | None:
        return self.models.get(f"{provider}/{model}")

    def calculate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
    ) -> float | None:
        pricing = self.get(provider, model)
        if pricing is None:
            key = (provider, model)
            with self._lock:
                if key not in self._warned:
                    self._warned.add(key)
                    logger.warning(
                        "telemetry pricing: no entry for provider=%r model=%r — cost_usd=null",
                        provider, model,
                    )
            return None

        billable_input = max(0, input_tokens - cache_read_tokens)
        cost = (
            billable_input * pricing.input_usd_per_1k_tokens / 1000.0
            + cache_read_tokens
            * pricing.input_usd_per_1k_tokens
            * pricing.cache_read_discount_factor
            / 1000.0
            + output_tokens * pricing.output_usd_per_1k_tokens / 1000.0
        )
        return round(cost, 8)


def load_pricing(path: str | Path) -> PricingTable:
    """Load a PricingTable from a yaml file. Returns an empty table if missing."""
    p = Path(path)
    if not p.exists():
        logger.warning("telemetry pricing: file not found: %s", p)
        return PricingTable()

    try:
        with p.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except Exception:
        logger.exception("telemetry pricing: failed to parse %s", p)
        return PricingTable()

    models_raw = raw.get("models", {}) or {}
    models: dict[str, ModelPricing] = {}
    for key, entry in models_raw.items():
        if not isinstance(entry, dict):
            logger.warning("telemetry pricing: skipping malformed entry %r", key)
            continue
        try:
            models[key] = ModelPricing(
                input_usd_per_1k_tokens=float(entry["input_usd_per_1k_tokens"]),
                output_usd_per_1k_tokens=float(entry["output_usd_per_1k_tokens"]),
                cache_read_discount_factor=float(
                    entry.get("cache_read_discount_factor", 0.1)
                ),
            )
        except (KeyError, TypeError, ValueError):
            logger.exception("telemetry pricing: bad entry %r", key)
            continue

    logger.info("telemetry pricing: loaded %d models from %s", len(models), p)
    return PricingTable(models=models)
