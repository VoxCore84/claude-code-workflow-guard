#!/usr/bin/env python3
"""
Async hook: log every tool use to JSONL for session analytics.

This script is invoked by Claude Code on PostToolUse (and optionally
PostToolUseFailure or Stop) events.  It appends a single JSON line to
~/.claude/session-stats.jsonl containing the timestamp, event type,
tool name, session id, and the first relevant file path from the
tool input.

The JSONL file is consumed by workflow-guard.py (Stop hook) to detect
workflow violations without any API calls.

Hook type : PostToolUse (async — does not block the agent)
Expects   : JSON on stdin with tool_name, tool_input, session_id, etc.
Writes to : ~/.claude/session-stats.jsonl
"""

import json
import os
import sys
from datetime import datetime, timezone


LOG_FILE = os.path.join(os.path.expanduser("~"), ".claude", "session-stats.jsonl")


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": data.get("hook_event_name", "unknown"),
        "tool": data.get("tool_name", ""),
        "session": data.get("session_id", ""),
    }

    # Extract the most relevant file path from tool_input.
    # Different tools use different key names; try the common ones.
    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        for key in ("file_path", "path", "pattern", "command"):
            value = tool_input.get(key)
            if value and isinstance(value, str):
                entry[key] = value
                break

    # Ensure the parent directory exists (first run on a fresh machine).
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never block the agent — logging is best-effort.


if __name__ == "__main__":
    main()
