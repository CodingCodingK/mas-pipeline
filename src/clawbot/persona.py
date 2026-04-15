"""Per-chat SOUL.md override writer for clawbot.

The only mutation point for persona files. Everything else (loading,
resolving, fallback to baseline) lives in `src.clawbot.prompt`.

Layout under `config/clawbot/personas/`:

    discord/<chat_id>/SOUL.md
    qq/<chat_id>/SOUL.md
    wechat/<chat_id>/SOUL.md

Path *is* the binding — (channel, chat_id) uniquely identifies a chat,
no mapping file. A missing override silently falls back to the baseline
SOUL.md; absence is the normal initial state for a new chat.

Write semantics:
  - Full-file replacement. LLM must pass the complete new SOUL body.
  - Directory is created on demand (mkdir -p).
  - Baseline `config/clawbot/SOUL.md` is never touched — writing there
    is explicitly blocked by path construction.
  - Concurrent writes to the same chat serialize behind a per-chat
    asyncio lock; cross-chat writes run in parallel.
"""

from __future__ import annotations

import asyncio
import logging

from src.clawbot.prompt import PERSONAS_DIR, SOUL_FILE_NAME, resolve_soul_path

logger = logging.getLogger(__name__)

_ALLOWED_CHANNELS = {"discord", "qq", "wechat"}
_MAX_SOUL_BYTES = 32 * 1024  # 32KB ceiling — SOUL is a persona, not a doc dump
_locks: dict[str, asyncio.Lock] = {}


def _lock_for(channel: str, chat_id: str) -> asyncio.Lock:
    key = f"{channel}:{chat_id}"
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


def _validate_chat_id(chat_id: str) -> None:
    """Reject chat_ids that would escape the persona directory.

    Discord/QQ/WeChat ids are numeric or short tokens — anything with
    path separators or `..` is an injection attempt.
    """
    if not chat_id:
        raise ValueError("chat_id is empty")
    if "/" in chat_id or "\\" in chat_id or ".." in chat_id:
        raise ValueError(f"chat_id contains illegal path characters: {chat_id!r}")
    if chat_id.startswith("."):
        raise ValueError(f"chat_id cannot start with '.': {chat_id!r}")


async def write_persona_soul(
    *,
    channel: str,
    chat_id: str,
    content: str,
) -> str:
    """Write a chat-scoped SOUL.md override.

    Args:
        channel: One of ``discord`` / ``qq`` / ``wechat``. Any other value
            is rejected; the baseline always wins for unknown channels.
        chat_id: Raw chat/group id from the bus. Validated against path
            traversal.
        content: Full replacement body for this chat's SOUL.md.

    Returns:
        Path (string) of the file that was written, for the tool's
        confirmation message.

    Raises:
        ValueError: on channel/chat_id/content validation failure.
        OSError: on filesystem failure.
    """
    if channel not in _ALLOWED_CHANNELS:
        raise ValueError(
            f"channel must be one of {sorted(_ALLOWED_CHANNELS)}, got {channel!r}"
        )
    _validate_chat_id(chat_id)

    if not isinstance(content, str) or not content.strip():
        raise ValueError("content must be a non-empty string")

    body = content.strip()
    body_bytes = body.encode("utf-8")
    if len(body_bytes) > _MAX_SOUL_BYTES:
        raise ValueError(
            f"content exceeds SOUL size ceiling "
            f"({len(body_bytes)} > {_MAX_SOUL_BYTES} bytes)"
        )

    target = PERSONAS_DIR / channel / chat_id / SOUL_FILE_NAME

    async with _lock_for(channel, chat_id):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body + "\n", encoding="utf-8")

    logger.info(
        "persona_write: wrote %d bytes to %s", len(body_bytes), target
    )
    return str(target)


async def edit_persona_soul(
    *,
    channel: str,
    chat_id: str,
    old_string: str,
    new_string: str,
) -> str:
    """Apply a unique string replacement to this chat's SOUL.md.

    Reads the currently-resolved SOUL (override if it exists, otherwise
    baseline), replaces exactly one occurrence of ``old_string`` with
    ``new_string``, and writes the result to the per-chat override path.
    The baseline file is never mutated — an edit against a chat with no
    prior override materializes a new override file by copying the
    baseline with the patch applied.

    Args:
        channel: One of ``discord`` / ``qq`` / ``wechat``.
        chat_id: Raw chat/group id from the bus.
        old_string: Exact substring to match. Must appear in the current
            SOUL exactly once — zero matches and multiple matches both
            raise ValueError so the LLM is forced to disambiguate.
        new_string: Replacement. May be empty (effectively a delete).

    Returns:
        Path (string) of the override file that was written.

    Raises:
        ValueError: on channel/chat_id/match validation failure.
        OSError: on filesystem failure.
    """
    if channel not in _ALLOWED_CHANNELS:
        raise ValueError(
            f"channel must be one of {sorted(_ALLOWED_CHANNELS)}, got {channel!r}"
        )
    _validate_chat_id(chat_id)

    if not isinstance(old_string, str) or old_string == "":
        raise ValueError("old_string must be a non-empty string")
    if not isinstance(new_string, str):
        raise ValueError("new_string must be a string")
    if old_string == new_string:
        raise ValueError("old_string and new_string are identical; nothing to change")

    source_path = resolve_soul_path(channel, chat_id)
    try:
        current = source_path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(
            f"cannot read current SOUL from {source_path}: {e}"
        ) from e

    occurrences = current.count(old_string)
    if occurrences == 0:
        raise ValueError(
            "old_string not found in current SOUL — make sure you copied it "
            "exactly (whitespace, punctuation, newlines all matter)"
        )
    if occurrences > 1:
        raise ValueError(
            f"old_string matches {occurrences} places — expand it with more "
            "surrounding context so exactly one match remains"
        )

    patched = current.replace(old_string, new_string, 1).strip()
    if not patched:
        raise ValueError(
            "patch would leave SOUL empty — use persona_write if you want a "
            "full replacement"
        )
    patched_bytes = patched.encode("utf-8")
    if len(patched_bytes) > _MAX_SOUL_BYTES:
        raise ValueError(
            f"patched SOUL exceeds size ceiling "
            f"({len(patched_bytes)} > {_MAX_SOUL_BYTES} bytes)"
        )

    target = PERSONAS_DIR / channel / chat_id / SOUL_FILE_NAME

    async with _lock_for(channel, chat_id):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(patched + "\n", encoding="utf-8")

    logger.info(
        "persona_edit: patched %s (source=%s, -%d +%d chars)",
        target,
        source_path,
        len(old_string),
        len(new_string),
    )
    return str(target)
