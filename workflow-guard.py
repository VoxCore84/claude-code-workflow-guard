#!/usr/bin/env python3
"""
Stop hook: workflow enforcement via fast Python heuristics.

Reads session activity from a JSONL log (written by session-stats.py) and
fires reminders when it detects common workflow violations:

  - Edited compiled files without a build/test reminder
  - Touched data files without an apply reminder
  - Modified config files without a restart reminder
  - Session appears to be ending without cleanup
  - Shared coordination files were modified

All checks are pure Python string matching -- zero API calls, zero tokens
burned, <50ms execution on any modern machine.

Hook type: Stop
Expects JSON on stdin with at least { "transcript_suffix": "..." }
Prints reminder lines to stdout (Claude Code displays them to the model).
Always exits 0 so the hook never blocks the agent.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _SCRIPT_DIR / "config.json"

_DEFAULT_CONFIG = {
    "file_categories": {
        "compiled": {
            "extensions": [".py", ".ts", ".cpp", ".h", ".rs", ".go"],
            "reminder": "remind user to test/build",
        },
        "data": {
            "extensions": [".sql", ".json"],
            "reminder": "remind about applying changes",
        },
        "config": {
            "extensions": [".yaml", ".toml", ".env"],
            "reminder": "remind about restarting services",
        },
    },
    "shared_files": ["session_state.md", "package.json", "Cargo.toml"],
    "session_ending_indicators": [
        "that should do it",
        "all done",
        "everything is complete",
        "let me know if",
        "anything else",
    ],
    "wrap_up_reminder": (
        "Session appears to be ending "
        "-- consider running /wrap-up or committing your changes."
    ),
    "lookback_minutes": 120,
}


def _load_config() -> dict:
    """Load config.json next to this script, falling back to defaults."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            user_cfg = json.load(fh)
        # Merge: user keys override defaults, missing keys keep defaults
        merged = dict(_DEFAULT_CONFIG)
        merged.update(user_cfg)
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Activity reader
# ---------------------------------------------------------------------------

def _stats_file_path() -> str:
    """Return the path to the session-stats JSONL file."""
    return os.path.join(os.path.expanduser("~"), ".claude", "session-stats.jsonl")


def _get_recent_activity(config: dict) -> dict:
    """
    Scan session-stats.jsonl for entries within the lookback window.

    Returns a dict with:
      - category_edits: { category_name: [file_path, ...] }
      - shared_file_edits: [file_path, ...]
      - tools_used: set of tool names
      - files_touched: [file_path, ...]
    """
    lookback = config.get("lookback_minutes", 120)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback)

    categories = config.get("file_categories", {})
    shared_patterns = [p.lower() for p in config.get("shared_files", [])]

    # Build extension -> category mapping for O(1) lookup
    ext_map: dict[str, str] = {}
    for cat_name, cat_def in categories.items():
        for ext in cat_def.get("extensions", []):
            ext_map[ext.lower()] = cat_name

    activity: dict = {
        "category_edits": {name: [] for name in categories},
        "shared_file_edits": [],
        "tools_used": set(),
        "files_touched": [],
    }

    stats_path = _stats_file_path()
    try:
        with open(stats_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Time filter
                ts_str = entry.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue

                # Track tool usage
                tool = entry.get("tool", "")
                if tool:
                    activity["tools_used"].add(tool)

                # File path extraction (handles both key names)
                file_path = entry.get("file_path", "") or entry.get("path", "")
                if not file_path:
                    continue

                activity["files_touched"].append(file_path)
                lower_path = file_path.lower()

                # Categorise by extension
                for ext, cat_name in ext_map.items():
                    if lower_path.endswith(ext):
                        activity["category_edits"][cat_name].append(file_path)
                        break

                # Shared file detection
                for pattern in shared_patterns:
                    if pattern in lower_path:
                        activity["shared_file_edits"].append(file_path)
                        break

    except FileNotFoundError:
        pass

    return activity


# ---------------------------------------------------------------------------
# Reminder logic
# ---------------------------------------------------------------------------

def _build_reminders(config: dict, activity: dict, transcript: str) -> list[str]:
    """
    Assemble a list of human-readable reminder strings based on the
    detected activity and transcript context.
    """
    reminders: list[str] = []
    categories = config.get("file_categories", {})

    # 1. Per-category file edit reminders
    for cat_name, cat_def in categories.items():
        edits = activity["category_edits"].get(cat_name, [])
        if not edits:
            continue
        basenames = sorted(set(os.path.basename(f) for f in edits))[:5]
        suffix = ", ..." if len(set(os.path.basename(f) for f in edits)) > 5 else ""
        reminder_text = cat_def.get("reminder", "check these files")
        reminders.append(
            f"{cat_name.capitalize()} files edited "
            f"({', '.join(basenames)}{suffix}) -- {reminder_text}."
        )

    # 2. Session-ending detection
    transcript_lower = transcript.lower()
    indicators = config.get("session_ending_indicators", [])
    if any(ind in transcript_lower for ind in indicators):
        wrap_msg = config.get(
            "wrap_up_reminder",
            "Session appears to be ending -- consider cleaning up.",
        )
        reminders.append(wrap_msg)

    # 3. Shared file warnings
    shared_edits = activity.get("shared_file_edits", [])
    if shared_edits:
        basenames = sorted(set(os.path.basename(f) for f in shared_edits))
        reminders.append(
            f"Shared files modified ({', '.join(basenames)}) "
            f"-- coordinate with other tabs/sessions."
        )

    return reminders


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    transcript = str(data.get("transcript_suffix", ""))
    config = _load_config()
    activity = _get_recent_activity(config)
    reminders = _build_reminders(config, activity, transcript)

    if reminders:
        print("WORKFLOW CHECK:")
        for r in reminders:
            print(f"  - {r}")

    sys.exit(0)


if __name__ == "__main__":
    main()
