"""pytest conftest for the scripts/ test suite.

On Windows the default asyncio loop is ``ProactorEventLoop`` but psycopg's
async driver requires ``SelectorEventLoop``. ``src/main.py`` already switches
the policy for the live API process; tests that hit async PG outside that
entry-point must do the same before pytest-asyncio spins up the event loop.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
