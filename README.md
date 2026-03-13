# Workflow Guard for Claude Code -- Fast Stop-Time Verification

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue) ![License: MIT](https://img.shields.io/github/license/VoxCore84/claude-code-workflow-guard) ![GitHub release](https://img.shields.io/github/v/release/VoxCore84/claude-code-workflow-guard)

A lightweight [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) hook that catches common workflow mistakes at stop time using pure Python heuristics. No API calls. No tokens burned. Under 50 ms.

## The Problem

The community pattern for stop-time verification calls a language model (typically Haiku) on every `Stop` event to ask "is the work complete?" This approach has three issues:

1. **Cost** -- every stop fires a paid API call, even when nothing interesting happened.
2. **Latency** -- an LLM round-trip adds 1-3 seconds to every pause in the conversation.
3. **Accuracy** -- a generic "is it done?" prompt has no awareness of what files were touched or what workflow your project actually follows.

## The Solution

Workflow Guard replaces the LLM call with fast Python heuristics that read a local JSONL activity log. It catches real, project-specific workflow violations:

- Edited `.cpp` / `.rs` / `.ts` files without a build reminder
- Touched `.sql` / `.json` data files without an apply reminder
- Modified `.yaml` / `.toml` / `.env` config without a restart reminder
- Session appears to be ending without cleanup (customizable phrase detection)
- Shared coordination files were modified (reminds to coordinate with other tabs)

All checks run in under 50 ms, use zero API calls, and burn zero tokens.

## Architecture

```
PostToolUse (async)          Stop (sync)
      |                          |
      v                          v
session-stats.py           workflow-guard.py
      |                          |
      v                          v
~/.claude/session-stats.jsonl    reads JSONL + transcript
      (append one line)          |
                                 v
                           stdout reminders
                           (shown to the model)
```

**session-stats.py** runs on every `PostToolUse` event. It appends a single JSON line recording the timestamp, tool name, and file path. This is async and non-blocking.

**workflow-guard.py** runs on `Stop` events. It scans recent JSONL entries (configurable time window), categorizes file edits, checks the transcript for session-ending phrases, and prints actionable reminders to stdout. Claude Code injects these reminders into the model's context.

## Installation

### 1. Copy the files

Clone or download this repo to a permanent location:

```bash
git clone https://github.com/VoxCore84/claude-code-workflow-guard.git ~/claude-code-workflow-guard
```

Or copy `workflow-guard.py`, `session-stats.py`, and `config.json` anywhere you like.

### 2. Configure your hooks

Add both hooks to your Claude Code settings. You can use either:

- **Project settings**: `.claude/settings.json` in your repo (team-wide)
- **User settings**: `~/.claude/settings.json` (personal, applies to all projects)

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "type": "command",
        "command": "python ~/claude-code-workflow-guard/session-stats.py",
        "timeout": 5000
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python ~/claude-code-workflow-guard/workflow-guard.py",
        "timeout": 5000
      }
    ]
  }
}
```

Replace the paths with wherever you placed the scripts. Use absolute paths.

### 3. Customize config.json

Edit `config.json` next to `workflow-guard.py` to match your project. See [Configuration](#configuration) below.

### 4. Verify

Start a Claude Code session, edit a few files, then check that `~/.claude/session-stats.jsonl` is growing. When the agent pauses, you should see `WORKFLOW CHECK:` reminders in the output.

## Configuration

All behavior is driven by `config.json` placed next to `workflow-guard.py`. If the file is missing or malformed, sensible defaults are used.

### `file_categories`

Define groups of file extensions and the reminder to show when files in that group are edited.

```json
"file_categories": {
  "compiled": {
    "extensions": [".py", ".ts", ".cpp", ".h", ".rs", ".go", ".java", ".cs", ".swift"],
    "reminder": "remind user to test/build"
  },
  "data": {
    "extensions": [".sql", ".json", ".csv"],
    "reminder": "remind about applying changes"
  },
  "config": {
    "extensions": [".yaml", ".yml", ".toml", ".env", ".ini", ".conf"],
    "reminder": "remind about restarting services"
  }
}
```

Add, remove, or rename categories freely. Each category is independent.

### `shared_files`

A list of filename substrings. If any edited file path contains one of these (case-insensitive), a coordination reminder fires.

```json
"shared_files": ["session_state.md", "package.json", "Cargo.toml"]
```

### `session_ending_indicators`

Phrases checked against the trailing transcript text (case-insensitive). If any match, the wrap-up reminder fires.

```json
"session_ending_indicators": [
  "that should do it",
  "all done",
  "everything is complete",
  "let me know if",
  "anything else"
]
```

### `wrap_up_reminder`

The exact text shown when a session-ending indicator is detected.

```json
"wrap_up_reminder": "Session appears to be ending -- consider running /wrap-up or committing your changes."
```

### `lookback_minutes`

How far back (in minutes) to scan the JSONL log. Default: `120`.

## Example Output

When the agent pauses after editing C++ and SQL files near the end of a session:

```
WORKFLOW CHECK:
  - Compiled files edited (RolePlay.cpp, RolePlay.h) -- remind user to test/build.
  - Data files edited (2026_03_11_01_world.sql) -- remind about applying changes.
  - Session appears to be ending -- consider running /wrap-up or committing your changes.
  - Shared files modified (session_state.md) -- coordinate with other tabs/sessions.
```

## Performance

| Metric | Workflow Guard | LLM-based stop hook |
|--------|---------------|-------------------|
| Execution time | <50 ms | 1-3 seconds |
| API calls per stop | 0 | 1 |
| Tokens per stop | 0 | ~500-1000 |
| Monthly cost (100 stops/day) | $0.00 | $3-15 |
| Accuracy | High (deterministic, project-specific) | Variable (generic prompt) |
| Offline capable | Yes | No |

Workflow Guard uses only Python standard library modules (`json`, `os`, `sys`, `datetime`, `pathlib`). No dependencies to install.

## Comparison: LLM-Based vs Heuristic Stop Hooks

**LLM-based** (the community pattern):
- Sends the entire transcript suffix to a model on every stop
- Asks a generic question like "is this work complete?"
- Model response is often vague ("looks like you're making progress")
- Burns real money on every pause, including mid-thought pauses
- Cannot run offline

**Heuristic-based** (this tool):
- Reads a local file, checks file extensions and string patterns
- Fires only when there is something specific to say
- Reminders are actionable: "you edited X, remember to Y"
- Free, instant, works offline
- Easy to customize per project via config.json

The two approaches are not mutually exclusive. You could run Workflow Guard for fast deterministic checks and add an LLM-based hook for a final session review.

## Files

| File | Purpose |
|------|--------|
| `workflow-guard.py` | Stop hook -- reads JSONL + transcript, prints reminders |
| `session-stats.py` | PostToolUse hook -- appends tool activity to JSONL |
| `config.json` | All configurable behavior (categories, patterns, phrases) |
| `settings.json.example` | Copy-paste snippet for Claude Code hook wiring |

## Requirements

- Python 3.8+
- Claude Code with hooks support

No third-party packages required.

> **Note:** [claude-code-compaction-keeper](https://github.com/VoxCore84/claude-code-compaction-keeper) also ships a `session-stats.py` implementation. If you install both, choose one `session-stats.py` to avoid duplicate JSONL logging.

## License

MIT -- see [LICENSE](LICENSE).

Built by [VoxCore84](https://github.com/VoxCore84).
