"""Unit tests for the task-notification XML format + metadata dict.

Covers tasks.md 7.2:
- format_task_notification renders all six fields in canonical order.
- Failed-status notifications still include statistics fields (even if 0).
- _build_notification_message metadata dict contains the three new keys.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tools.builtins.spawn_agent import (
    _build_notification_message,
    format_task_notification,
)

FAILED = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global FAILED
    if condition:
        print(f"  [PASS] {label}", flush=True)
    else:
        FAILED += 1
        print(f"  [FAIL] {label} — {detail}", flush=True)


print("\n=== 1. format_task_notification — all six fields in order ===")
xml = format_task_notification(
    agent_run_id=42,
    role="writer",
    status="completed",
    result="draft body",
    tool_use_count=3,
    total_tokens=1234,
    duration_ms=5678,
)
check("contains agent-run-id", "<agent-run-id>42</agent-run-id>" in xml)
check("contains role", "<role>writer</role>" in xml)
check("contains status", "<status>completed</status>" in xml)
check("contains tool-use-count", "<tool-use-count>3</tool-use-count>" in xml)
check("contains total-tokens", "<total-tokens>1234</total-tokens>" in xml)
check("contains duration-ms", "<duration-ms>5678</duration-ms>" in xml)
check("contains result", "<result>draft body</result>" in xml)

# Canonical ordering: id → role → status → stats → result
def _idx(tag: str) -> int:
    return xml.index(f"<{tag}>")

order = [
    _idx("agent-run-id"),
    _idx("role"),
    _idx("status"),
    _idx("tool-use-count"),
    _idx("total-tokens"),
    _idx("duration-ms"),
    _idx("result"),
]
check("fields in canonical order", order == sorted(order),
      f"got indices {order}")


print("\n=== 2. Failed notification still has stats (possibly 0) ===")
failed_xml = format_task_notification(
    agent_run_id=7,
    role="analyst",
    status="failed",
    result="[ERROR] boom",
    tool_use_count=0,
    total_tokens=0,
    duration_ms=0,
)
check("failed has status", "<status>failed</status>" in failed_xml)
check("failed has tool-use-count 0", "<tool-use-count>0</tool-use-count>" in failed_xml)
check("failed has total-tokens 0", "<total-tokens>0</total-tokens>" in failed_xml)
check("failed has duration-ms 0", "<duration-ms>0</duration-ms>" in failed_xml)


print("\n=== 3. _build_notification_message metadata contains new keys ===")
msg = _build_notification_message(
    agent_run_id=99,
    role="reviewer",
    status="completed",
    result="LGTM",
    tool_use_count=5,
    total_tokens=2048,
    duration_ms=12345,
)
check("message role user", msg["role"] == "user")
check("metadata kind task_notification", msg["metadata"]["kind"] == "task_notification")
check("metadata agent_run_id", msg["metadata"]["agent_run_id"] == 99)
check("metadata tool_use_count", msg["metadata"]["tool_use_count"] == 5)
check("metadata total_tokens", msg["metadata"]["total_tokens"] == 2048)
check("metadata duration_ms", msg["metadata"]["duration_ms"] == 12345)
check("metadata status", msg["metadata"]["status"] == "completed")
check("metadata sub_agent_role", msg["metadata"]["sub_agent_role"] == "reviewer")


print("\n" + "=" * 50)
if FAILED:
    print(f"FAILED: {FAILED}")
    sys.exit(1)
print("All task-notification format checks passed!")
