"""Session history full-load test: no silent truncation.

align-compact-with-cc: get_session_history must return the full JSONB array.
CC's loadFullLog does the same — truncating on load would hide early turns
from the compact layer entirely.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

passed = 0
failed = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} -- {detail}")


print("\n=== get_session_history full load (1500 msgs) ===")


async def test_full_load():
    from src.bus.session import get_session_history

    # Seed: 1500 alternating user/assistant messages
    messages = []
    for i in range(1500):
        role = "user" if i % 2 == 0 else "assistant"
        messages.append({"role": role, "content": f"msg {i}"})

    with (
        patch("src.bus.session.get_messages", new_callable=AsyncMock, return_value=messages),
        patch("src.bus.session.clean_orphan_messages", side_effect=lambda m: m),
    ):
        history = await get_session_history(conversation_id=1)

    check("Full 1500 returned", len(history) == 1500)
    check("Head preserved", history[0]["content"] == "msg 0")
    check("Tail preserved", history[-1]["content"] == "msg 1499")


asyncio.run(test_full_load())


async def test_full_load_with_leading_tool():
    """Leading tool-role messages are still stripped, but nothing else is capped."""
    from src.bus.session import get_session_history

    messages = [
        {"role": "tool", "content": "orphan 1"},
        {"role": "tool", "content": "orphan 2"},
    ] + [{"role": "user", "content": f"m{i}"} for i in range(500)]

    with (
        patch("src.bus.session.get_messages", new_callable=AsyncMock, return_value=messages),
        patch("src.bus.session.clean_orphan_messages", side_effect=lambda m: m),
    ):
        history = await get_session_history(conversation_id=1)

    check("Leading tool-role stripped", len(history) == 500)
    check("First is user m0", history[0] == {"role": "user", "content": "m0"})


asyncio.run(test_full_load_with_leading_tool())


print(f"\n{'='*50}")
print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
if failed:
    sys.exit(1)
print("All checks passed!")
