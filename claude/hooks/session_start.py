#!/usr/bin/env python3
"""SessionStart hook: tells Claude which gateway it runs through and what Allinone offers.

Claude Code adds whatever this script prints to the conversation as context.
Edit claude/context.md to change the instructions; this script only fills in
the session details and the latest memory notes.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(os.environ.get("ALLINONE_ROOT") or Path(__file__).resolve().parents[2])


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        event = {}
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    values = {
        "gateway": os.environ.get("ALLINONE_GATEWAY_TITLE") or os.environ.get("ALLINONE_GATEWAY") or "?",
        "gateway_url": os.environ.get("ALLINONE_GATEWAY_URL", ""),
        "model": os.environ.get("ALLINONE_MODEL") or "gateway default",
        "language": {"ar": "Arabic", "en": "English"}.get(os.environ.get("ALLINONE_LANG", ""), "the user's language"),
        "source": event.get("source", ""),
    }
    template_path = ROOT / "claude" / "context.md"
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError:
        template = "This session runs through the {gateway} gateway ({gateway_url})."
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))

    notes = recent_notes(int(os.environ.get("ALLINONE_CONTEXT_NOTES", "5")))
    if notes:
        text += "\n\nRecent Allinone memory notes (use memory_search for more):\n" + "\n".join(notes)
    print(text.strip())
    return 0


def recent_notes(limit: int):
    db = Path(os.environ.get("ALLINONE_DB") or ROOT / "data" / "allinone.db")
    if limit <= 0 or not db.exists():
        return []
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=3)
        try:
            rows = conn.execute("SELECT id, text FROM memory ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [f"- #{i}: {t[:300]}" for i, t in rows]


if __name__ == "__main__":
    sys.exit(main())
