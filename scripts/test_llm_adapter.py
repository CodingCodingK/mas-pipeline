"""Verify LLM adapter: route a model, call it, print the LLMResponse."""

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.router import route


async def main():
    # Use the 'light' tier (gpt-4o-mini by default) — cheapest option for testing
    model = sys.argv[1] if len(sys.argv) > 1 else "light"
    print(f"Routing model: {model}")

    adapter = route(model)
    print(f"Adapter: {adapter.__class__.__name__} (model={adapter.model})")

    messages = [{"role": "user", "content": "Say hello in one sentence."}]
    print("Calling LLM...")

    response = await adapter.call(messages, max_tokens=100)
    print(f"\n--- LLMResponse ---")
    print(f"content: {response.content}")
    print(f"finish_reason: {response.finish_reason}")
    print(f"tool_calls: {response.tool_calls}")
    print(f"usage: input={response.usage.input_tokens}, output={response.usage.output_tokens}, thinking={response.usage.thinking_tokens}")
    print(f"thinking: {response.thinking}")


if __name__ == "__main__":
    asyncio.run(main())
