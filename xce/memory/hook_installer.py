"""XME Hook Installer — writes Kiro and Claude Code hook configs.

Run:
    python -m xce memory hooks install /path/to/repo

This writes:
  .kiro/hooks/xme-session-end.json
  .kiro/hooks/xme-record-turn.json
  .kiro/hooks/xme-record-tool.json
  .claude/settings.json   (merged — never overwrites existing hooks)

All paths are absolute and based on the repo root + the active venv python.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _python_exe() -> str:
    """Return the Python interpreter to use in hook commands."""
    # Prefer the venv python if running inside one
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        candidate = Path(venv) / "bin" / "python"
        if candidate.exists():
            return str(candidate)
    return sys.executable


def install_hooks(repo_path: str, *, dry_run: bool = False) -> dict[str, list[str]]:
    """Install all XME hooks for the given repo.

    Returns a dict of {tool: [files written]}.
    """
    repo = Path(repo_path).resolve()
    python = _python_exe()
    cmd_base = f"{python} -m xce.memory.hook_handler --repo-path {repo}"

    written: dict[str, list[str]] = {"kiro": [], "claude": []}

    # ---------------------------------------------------------------
    # Kiro hooks
    # ---------------------------------------------------------------
    kiro_hooks_dir = repo / ".kiro" / "hooks"
    if not dry_run:
        kiro_hooks_dir.mkdir(parents=True, exist_ok=True)

    kiro_hook_defs = [
        {
            "filename": "xme-session-end.json",
            "content": {
                "name": "XME Session End",
                "version": "1.0.0",
                "description": (
                    "Flush and compact the XME memory journal when Kiro stops. "
                    "Extracts decisions, failures, and preferences into the graph."
                ),
                "when": {"type": "agentStop"},
                "then": {
                    "type": "runCommand",
                    "command": f"{cmd_base} --event agentStop",
                    "timeout": 15,
                },
            },
        },
        {
            "filename": "xme-record-turn.json",
            "content": {
                "name": "XME Record Prompt",
                "version": "1.0.0",
                "description": (
                    "Record each user prompt in the XME daily journal "
                    "for later compaction into the memory graph."
                ),
                "when": {"type": "promptSubmit"},
                "then": {
                    "type": "runCommand",
                    "command": f"{cmd_base} --event promptSubmit",
                    "timeout": 5,
                },
            },
        },
        {
            "filename": "xme-record-tool.json",
            "content": {
                "name": "XME Record Tool Call",
                "version": "1.0.0",
                "description": (
                    "Record tool calls in the XME daily journal after each execution. "
                    "Skips XME meta-tools to avoid circular journaling."
                ),
                "when": {
                    "type": "postToolUse",
                    "toolTypes": ["read", "write", "shell", "web"],
                },
                "then": {
                    "type": "runCommand",
                    "command": f"{cmd_base} --event postToolUse",
                    "timeout": 5,
                },
            },
        },
    ]

    for hook_def in kiro_hook_defs:
        hook_file = kiro_hooks_dir / hook_def["filename"]
        if not dry_run:
            hook_file.write_text(
                json.dumps(hook_def["content"], indent=2), encoding="utf-8"
            )
        written["kiro"].append(str(hook_file))

    # ---------------------------------------------------------------
    # Claude Code hooks (.claude/settings.json)
    # ---------------------------------------------------------------
    claude_dir = repo / ".claude"
    claude_settings = claude_dir / "settings.json"

    if not dry_run:
        claude_dir.mkdir(exist_ok=True)

    # Build XME hook entries
    xme_hooks = {
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{cmd_base} --event Stop",
                    }
                ],
            }
        ],
        "UserPromptSubmit": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{cmd_base} --event UserPromptSubmit",
                    }
                ],
            }
        ],
        "PostToolUse": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{cmd_base} --event PostToolUse",
                    }
                ],
            }
        ],
    }

    # Merge into existing settings (never overwrite user's custom hooks)
    existing: dict = {}
    if claude_settings.exists():
        try:
            existing = json.loads(claude_settings.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    existing_hooks: dict = existing.get("hooks", {})
    for event, entries in xme_hooks.items():
        if event not in existing_hooks:
            existing_hooks[event] = entries
        else:
            # Check if XME hook already there by command prefix
            cmds = [
                h["command"]
                for block in existing_hooks[event]
                for h in block.get("hooks", [])
            ]
            xme_cmd = entries[0]["hooks"][0]["command"]
            if not any("xme.memory.hook_handler" in c for c in cmds):
                existing_hooks[event].extend(entries)

    existing["hooks"] = existing_hooks

    if not dry_run:
        claude_settings.write_text(
            json.dumps(existing, indent=2), encoding="utf-8"
        )
    written["claude"].append(str(claude_settings))

    return written


def uninstall_hooks(repo_path: str) -> dict[str, list[str]]:
    """Remove all XME hook files and entries."""
    repo = Path(repo_path).resolve()
    removed: dict[str, list[str]] = {"kiro": [], "claude": []}

    # Remove Kiro hook files
    for name in ("xme-session-end.json", "xme-record-turn.json", "xme-record-tool.json"):
        f = repo / ".kiro" / "hooks" / name
        if f.exists():
            f.unlink()
            removed["kiro"].append(str(f))

    # Remove XME entries from .claude/settings.json
    claude_settings = repo / ".claude" / "settings.json"
    if claude_settings.exists():
        try:
            data = json.loads(claude_settings.read_text(encoding="utf-8"))
            hooks = data.get("hooks", {})
            for event in list(hooks.keys()):
                hooks[event] = [
                    block for block in hooks[event]
                    if not any(
                        "xme.memory.hook_handler" in h.get("command", "")
                        for h in block.get("hooks", [])
                    )
                ]
                if not hooks[event]:
                    del hooks[event]
            data["hooks"] = hooks
            claude_settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
            removed["claude"].append(str(claude_settings))
        except Exception as e:
            print(f"Warning: could not clean .claude/settings.json: {e}", file=sys.stderr)

    return removed
