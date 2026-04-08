"""Memory relevance selection via light-tier LLM judgment."""

from __future__ import annotations

import json
import logging

from src.llm.router import route
from src.memory.store import get_memory, list_memories

logger = logging.getLogger(__name__)

_RELEVANCE_PROMPT = """\
You are a memory relevance judge. Given a query and a list of memory summaries, \
return a JSON array of memory IDs that are relevant to the query.

Return ONLY the JSON array, no other text. Example: [3, 7, 1]
If none are relevant, return an empty array: []

Order by relevance (most relevant first).

Query: {query}

Memories:
{memory_list}
"""


async def select_relevant(
    project_id: int,
    query: str,
    limit: int = 5,
) -> list:
    """Select memories relevant to query using LLM judgment.

    Returns list of full Memory ORM objects, ordered by relevance.
    """
    memories = await list_memories(project_id)
    if not memories:
        return []

    # Build memory list for LLM
    lines = []
    for mem in memories:
        lines.append(f"- ID={mem.id} [{mem.type}] {mem.name}: {mem.description}")
    memory_list = "\n".join(lines)

    prompt = _RELEVANCE_PROMPT.format(query=query, memory_list=memory_list)

    # Call light-tier LLM
    adapter = route("light")
    response = await adapter.call(
        [{"role": "user", "content": prompt}],
        tools=[],
    )

    # Parse LLM response as JSON array of IDs
    try:
        raw = response.content.strip()
        # Handle markdown code blocks
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        selected_ids = json.loads(raw)
        if not isinstance(selected_ids, list):
            selected_ids = []
    except (json.JSONDecodeError, AttributeError):
        logger.warning("LLM returned non-JSON for memory selection: %s", response.content)
        return []

    # Fetch full memory objects for selected IDs, up to limit
    result = []
    for mid in selected_ids[:limit]:
        try:
            mem = await get_memory(int(mid))
            result.append(mem)
        except Exception:
            continue

    return result
