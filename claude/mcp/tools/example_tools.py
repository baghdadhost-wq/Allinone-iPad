"""Example user tools — copy this file and write your own.

Every function decorated with @tool becomes a tool Claude Code can call
(it appears as mcp__allinone__<function name>). Restart Claude Code to load
changes. Delete or rename this file (prefix it with _) to disable the examples.
"""

from __future__ import annotations

import datetime
import json
import platform
import urllib.request

from mcp_kit import tool


@tool
def current_time(timezone_offset_hours: float = 3.0) -> str:
    """Current date and time. `timezone_offset_hours` is the UTC offset (3 = Baghdad)."""
    tz = datetime.timezone(datetime.timedelta(hours=timezone_offset_hours))
    return datetime.datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S (UTC%z)")


@tool
def system_info() -> dict:
    """Basic facts about this computer (OS, CPU architecture, Python version)."""
    return {"os": platform.platform(), "machine": platform.machine(), "python": platform.python_version()}


@tool
def http_get_json(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return its body (JSON pretty-printed when possible). For quick API checks."""
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "allinone"}), timeout=20) as r:
        text = r.read().decode("utf-8", "replace")
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        pass
    return text[: int(max_chars)]
