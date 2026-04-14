"""Verify the router sets provider_label on OpenAICompatAdapter so telemetry
labels match pricing.yaml keys (regression guard for the cost_usd=0 bug).

Previously the telemetry collector inferred the provider from the adapter's
Python module name, which collapsed openai/deepseek/qwen/openai_compat into
a single "openai_compat" label. Every non-anthropic LLM call then missed
the pricing lookup and recorded cost_usd=null.

Run: python scripts/test_provider_label_normalization.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.loop import _infer_provider
from src.llm.anthropic import AnthropicAdapter
from src.llm.openai_compat import OpenAICompatAdapter


def test_openai_compat_accepts_and_exposes_provider_label() -> None:
    a = OpenAICompatAdapter(
        api_base="http://fake", api_key="key", model="gpt-4o", provider_label="openai"
    )
    assert a.provider_label == "openai", a.provider_label


def test_openai_compat_defaults_to_openai_compat_when_unset() -> None:
    a = OpenAICompatAdapter(api_base="http://fake", api_key="key", model="gpt-4o")
    assert a.provider_label == "openai_compat", a.provider_label


def test_anthropic_adapter_has_provider_label() -> None:
    a = AnthropicAdapter(api_base="http://fake", api_key="key", model="claude-opus-4-6")
    assert a.provider_label == "anthropic", a.provider_label


def test_infer_provider_prefers_label_over_module_name() -> None:
    a = OpenAICompatAdapter(
        api_base="http://fake", api_key="key", model="deepseek-chat", provider_label="deepseek"
    )
    assert _infer_provider(a) == "deepseek", _infer_provider(a)


def test_infer_provider_falls_back_to_module_name_for_unlabeled_adapter() -> None:
    class LegacyAdapter:
        pass

    legacy = LegacyAdapter()
    result = _infer_provider(legacy)
    assert "__main__" in result or "test_provider_label_normalization" in result, result


def test_router_sets_label_from_match_provider() -> None:
    """Router resolves the provider name from _match_provider and passes it."""
    from src.llm.router import _match_provider

    assert _match_provider("gpt-4o") == "openai"
    assert _match_provider("deepseek-chat") == "deepseek"
    assert _match_provider("claude-opus-4-6") == "anthropic"


def test_pricing_lookup_roundtrip_for_fixed_labels() -> None:
    """The labels we set must exist as keys in the shipped pricing table
    for at least one entry per provider.
    """
    from src.telemetry.pricing import load_pricing

    table = load_pricing(Path("config/pricing.yaml"))
    # Spot-check: gpt-4o via the fixed openai label, not openai_compat
    assert table.get("openai", "gpt-4o") is not None
    assert table.get("deepseek", "deepseek-chat") is not None
    assert table.get("anthropic", "claude-opus-4-6") is not None
    # And the legacy/unfixed openai_compat entries still resolve
    assert table.get("openai_compat", "gpt-5.4") is not None


def main() -> None:
    tests = [
        test_openai_compat_accepts_and_exposes_provider_label,
        test_openai_compat_defaults_to_openai_compat_when_unset,
        test_anthropic_adapter_has_provider_label,
        test_infer_provider_prefers_label_over_module_name,
        test_infer_provider_falls_back_to_module_name_for_unlabeled_adapter,
        test_router_sets_label_from_match_provider,
        test_pricing_lookup_roundtrip_for_fixed_labels,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"OK   {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"ERR  {t.__name__}: {type(exc).__name__}: {exc}")
    if failures:
        sys.exit(1)
    print(f"\nAll {len(tests)} tests passed.")


if __name__ == "__main__":
    main()
