"""Git hook installer for XCE — auto-index a repository after each commit.

Installs a git ``post-commit`` hook that triggers an incremental (diff-based)
re-index so the Neo4j knowledge graph stays in sync with the working tree
without any manual ``xanther index`` runs.

Usage:
    xanther git-hook install /path/to/repo
    xanther git-hook uninstall /path/to/repo

The generated hook runs::

    xanther index <repo> --diff --mode xme

``--diff`` limits parsing to files changed in the last commit and ``--mode xme``
keeps the hook fast (AST + embeddings + memory sync, no LLM doc generation) so
it does not block the developer's commit flow. The indexing runs in the
background and its output is appended to ``.xanther/post-commit.log``.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

# Marker lines so we can safely detect and remove only our own hook block,
# even when a user already has an existing post-commit hook.
HOOK_BEGIN = "# >>> xanther post-commit auto-index >>>"
HOOK_END = "# <<< xanther post-commit auto-index <<<"


def _git_dir(repo: Path) -> Path | None:
    """Return the ``.git`` directory for ``repo`` (handles worktrees/submodules).

    Supports the common case where ``.git`` is a directory as well as the
    worktree/submodule case where ``.git`` is a file pointing elsewhere.
    """
    git_path = repo / ".git"
    if git_path.is_dir():
        return git_path
    if git_path.is_file():
        # `.git` file: `gitdir: <path>`
        try:
            content = git_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        prefix = "gitdir:"
        if content.startswith(prefix):
            target = content[len(prefix):].strip()
            resolved = (repo / target).resolve() if not os.path.isabs(target) else Path(target)
            return resolved
    return None


def _xanther_exe() -> str:
    """Return the ``xanther`` console script path, preferring the active venv."""
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        candidate = Path(venv) / "bin" / "xanther"
        if candidate.exists():
            return str(candidate)
    # Fall back to a xanther next to the running interpreter, else PATH lookup.
    candidate = Path(sys.executable).parent / "xanther"
    if candidate.exists():
        return str(candidate)
    return "xanther"


def _hook_block(repo: Path, *, mode: str = "xme") -> str:
    """Build the shell block injected into the git post-commit hook."""
    xanther = _xanther_exe()
    repo_str = str(repo.resolve())
    log = ".xanther/post-commit.log"
    return (
        f"{HOOK_BEGIN}\n"
        f"# Incrementally re-index changed files and update Neo4j after each commit.\n"
        f'mkdir -p "{repo_str}/.xanther"\n'
        f"(\n"
        f'  cd "{repo_str}" && \\\n'
        f'  "{xanther}" index "{repo_str}" --diff --mode {mode} \\\n'
        f'    >> "{repo_str}/{log}" 2>&1\n'
        f") &\n"
        f"{HOOK_END}\n"
    )


def install_git_hook(repo_path: str, *, mode: str = "xme", dry_run: bool = False) -> str:
    """Install the XCE post-commit auto-index hook into ``repo_path``.

    Returns the path to the installed hook file.

    Raises:
        FileNotFoundError: if ``repo_path`` is not a git repository.
    """
    repo = Path(repo_path).resolve()
    git_dir = _git_dir(repo)
    if git_dir is None:
        raise FileNotFoundError(f"{repo} is not a git repository (no .git found)")

    hooks_dir = git_dir / "hooks"
    hook_file = hooks_dir / "post-commit"
    block = _hook_block(repo, mode=mode)

    if dry_run:
        return str(hook_file)

    hooks_dir.mkdir(parents=True, exist_ok=True)

    if hook_file.exists():
        existing = hook_file.read_text(encoding="utf-8")
        # Replace any prior xanther block to keep the hook idempotent.
        if HOOK_BEGIN in existing and HOOK_END in existing:
            existing = _strip_block(existing)
        # Ensure the file starts with a shebang.
        if not existing.startswith("#!"):
            existing = "#!/bin/sh\n" + existing
        new_content = existing.rstrip("\n") + "\n\n" + block
    else:
        new_content = "#!/bin/sh\n\n" + block

    hook_file.write_text(new_content, encoding="utf-8")
    # Make the hook executable (git requires this).
    mode_bits = hook_file.stat().st_mode
    hook_file.chmod(mode_bits | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return str(hook_file)


def uninstall_git_hook(repo_path: str) -> str | None:
    """Remove the XCE post-commit hook block from ``repo_path``.

    Returns the hook path if a change was made, otherwise ``None``.
    """
    repo = Path(repo_path).resolve()
    git_dir = _git_dir(repo)
    if git_dir is None:
        return None

    hook_file = git_dir / "hooks" / "post-commit"
    if not hook_file.exists():
        return None

    content = hook_file.read_text(encoding="utf-8")
    if HOOK_BEGIN not in content:
        return None

    stripped = _strip_block(content)
    # If nothing but the shebang remains, remove the file entirely.
    if stripped.strip() in ("", "#!/bin/sh"):
        hook_file.unlink()
    else:
        hook_file.write_text(stripped, encoding="utf-8")

    return str(hook_file)


def _strip_block(content: str) -> str:
    """Remove the xanther-managed block (inclusive of markers) from ``content``."""
    lines = content.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.strip() == HOOK_BEGIN:
            skipping = True
            continue
        if line.strip() == HOOK_END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    # Collapse trailing blank lines to a single newline.
    return "\n".join(out).rstrip("\n") + "\n"
