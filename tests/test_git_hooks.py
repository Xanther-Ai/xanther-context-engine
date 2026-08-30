"""Tests for the post-commit auto-index git hook installer.

Validates:
- Install writes an executable post-commit hook containing the xanther block
- Install is idempotent (re-install replaces the prior block, no duplicates)
- Install preserves a user's pre-existing hook content
- Uninstall removes only the xanther block (and the file if nothing else remains)
- Worktree/submodule `.git` file indirection is resolved
- Non-git directories raise FileNotFoundError
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from xce.git_hooks import (
    HOOK_BEGIN,
    HOOK_END,
    install_git_hook,
    uninstall_git_hook,
)


def _make_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo layout (.git/hooks) without invoking git."""
    repo = tmp_path / "repo"
    (repo / ".git" / "hooks").mkdir(parents=True)
    return repo


class TestInstall:
    def test_install_creates_executable_hook(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        hook_file = install_git_hook(str(repo))

        p = Path(hook_file)
        assert p.exists()
        assert p.name == "post-commit"

        content = p.read_text()
        assert content.startswith("#!/bin/sh")
        assert HOOK_BEGIN in content
        assert HOOK_END in content
        assert "xanther" in content and "index" in content and "--diff" in content

        # Executable bit set for the user.
        assert p.stat().st_mode & stat.S_IXUSR

    def test_install_default_mode_is_xme(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        content = Path(install_git_hook(str(repo))).read_text()
        assert "--mode xme" in content

    def test_install_respects_mode(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        content = Path(install_git_hook(str(repo), mode="full")).read_text()
        assert "--mode full" in content

    def test_dry_run_does_not_write(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        hook_file = install_git_hook(str(repo), dry_run=True)
        assert not Path(hook_file).exists()

    def test_install_is_idempotent(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        install_git_hook(str(repo))
        hook_file = install_git_hook(str(repo))  # second install

        content = Path(hook_file).read_text()
        # Exactly one managed block after re-install.
        assert content.count(HOOK_BEGIN) == 1
        assert content.count(HOOK_END) == 1

    def test_install_preserves_existing_hook(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        hook_file = repo / ".git" / "hooks" / "post-commit"
        hook_file.write_text("#!/bin/sh\necho 'my custom hook'\n")

        install_git_hook(str(repo))
        content = hook_file.read_text()
        assert "my custom hook" in content
        assert HOOK_BEGIN in content

    def test_install_rejects_non_git_dir(self, tmp_path: Path):
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()
        with pytest.raises(FileNotFoundError):
            install_git_hook(str(not_a_repo))


class TestGitFileIndirection:
    def test_resolves_gitdir_file(self, tmp_path: Path):
        """Worktree/submodule case: .git is a file pointing at the real gitdir."""
        repo = tmp_path / "worktree"
        repo.mkdir()
        real_gitdir = tmp_path / "actual_git"
        (real_gitdir / "hooks").mkdir(parents=True)
        (repo / ".git").write_text(f"gitdir: {real_gitdir}\n")

        hook_file = install_git_hook(str(repo))
        assert Path(hook_file).exists()
        assert Path(hook_file).parent == real_gitdir / "hooks"


class TestUninstall:
    def test_uninstall_removes_file_when_only_block(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        install_git_hook(str(repo))
        removed = uninstall_git_hook(str(repo))

        assert removed is not None
        # File is deleted because only the shebang + our block existed.
        assert not Path(removed).exists()

    def test_uninstall_preserves_other_hook_content(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        hook_file = repo / ".git" / "hooks" / "post-commit"
        hook_file.write_text("#!/bin/sh\necho 'keep me'\n")
        install_git_hook(str(repo))

        uninstall_git_hook(str(repo))
        content = hook_file.read_text()
        assert "keep me" in content
        assert HOOK_BEGIN not in content
        assert HOOK_END not in content

    def test_uninstall_no_hook_returns_none(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        assert uninstall_git_hook(str(repo)) is None

    def test_uninstall_non_git_returns_none(self, tmp_path: Path):
        not_a_repo = tmp_path / "plain"
        not_a_repo.mkdir()
        assert uninstall_git_hook(str(not_a_repo)) is None

    def test_uninstall_hook_without_our_block_returns_none(self, tmp_path: Path):
        repo = _make_repo(tmp_path)
        hook_file = repo / ".git" / "hooks" / "post-commit"
        hook_file.write_text("#!/bin/sh\necho hi\n")
        assert uninstall_git_hook(str(repo)) is None
