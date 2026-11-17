"""Thin wrappers around the ``git`` CLI. Failures raise GitError carrying git's own message."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise GitError("git is not installed or not on PATH (or the directory does not exist)") from e
    except NotADirectoryError as e:
        raise GitError(f"{cwd} is not a directory") from e
    if check and proc.returncode != 0:
        raise GitError((proc.stderr or proc.stdout).strip() or f"git {' '.join(args)} failed")
    return proc


@dataclass
class Worktree:
    path: Path
    head: str = ""
    branch: str = ""  # short name; empty when detached
    detached: bool = False
    bare: bool = False
    locked: bool = False
    prunable: bool = False
    is_main: bool = False
    # Filled by add_status():
    dirty: int = 0
    ahead: int | None = None
    behind: int | None = None

    @property
    def label(self) -> str:
        if self.bare:
            return "(bare)"
        return self.branch or f"(detached {self.head[:7]})"

    @property
    def state(self) -> str:
        if self.prunable:
            return "missing"
        parts: list[str] = []
        if self.dirty:
            parts.append(f"{self.dirty} changed")
        if self.ahead:
            parts.append(f"↑{self.ahead}")
        if self.behind:
            parts.append(f"↓{self.behind}")
        if self.locked:
            parts.append("locked")
        return " ".join(parts) if parts else "clean"


def parse_porcelain(text: str) -> list[Worktree]:
    """Parse ``git worktree list --porcelain``. The first entry is the main worktree."""
    result: list[Worktree] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        if not block.strip():
            continue
        wt = Worktree(path=Path())
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            if key == "worktree":
                wt.path = Path(value)
            elif key == "HEAD":
                wt.head = value
            elif key == "branch":
                wt.branch = value.removeprefix("refs/heads/")
            elif key == "detached":
                wt.detached = True
            elif key == "bare":
                wt.bare = True
            elif key == "locked":
                wt.locked = True
            elif key == "prunable":
                wt.prunable = True
        result.append(wt)
    if result:
        result[0].is_main = True
    return result


def is_repo(path: Path) -> bool:
    try:
        return _git(path, "rev-parse", "--git-dir", check=False).returncode == 0
    except GitError:
        return False


def toplevel(path: Path) -> Path:
    """Main worktree root for any path inside a repo or one of its worktrees."""
    common = Path(_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    return common.parent if common.name == ".git" else common


def list_worktrees(repo: Path, with_status: bool = True) -> list[Worktree]:
    worktrees = parse_porcelain(_git(repo, "worktree", "list", "--porcelain").stdout)
    if with_status:
        for wt in worktrees:
            add_status(wt)
    return worktrees


def add_status(wt: Worktree) -> None:
    if wt.bare or wt.prunable or not wt.path.is_dir():
        return
    status = _git(wt.path, "status", "--porcelain", check=False)
    if status.returncode == 0:
        wt.dirty = len([ln for ln in status.stdout.splitlines() if ln.strip()])
    counts = _git(wt.path, "rev-list", "--left-right", "--count", "@{upstream}...HEAD", check=False)
    if counts.returncode == 0:
        behind, ahead = counts.stdout.split()
        wt.behind, wt.ahead = int(behind), int(ahead)


def _ref_exists(repo: Path, ref: str) -> bool:
    return _git(repo, "show-ref", "--verify", "--quiet", ref, check=False).returncode == 0


def default_worktree_dir(root: Path, branch: str) -> Path:
    return root / branch.replace("/", "-")


def add_worktree(repo: Path, dest: Path, branch: str, base: str = "") -> str:
    """Create a worktree for ``branch`` at ``dest`` and describe what was done.

    Uses the local branch if it exists, else tracks ``origin/<branch>`` if that exists,
    else creates a new branch from ``base`` (default: HEAD of the main worktree).
    """
    if dest.exists():
        raise GitError(f"{dest} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if _ref_exists(repo, f"refs/heads/{branch}"):
        _git(repo, "worktree", "add", str(dest), branch)
        return f"checked out existing branch {branch}"
    if _ref_exists(repo, f"refs/remotes/origin/{branch}"):
        _git(repo, "worktree", "add", "--track", "-b", branch, str(dest), f"origin/{branch}")
        return f"created {branch} tracking origin/{branch}"
    args = ["worktree", "add", "-b", branch, str(dest)]
    if base:
        args.append(base)
    _git(repo, *args)
    return f"created new branch {branch}" + (f" from {base}" if base else "")


def remove_worktree(repo: Path, wt: Worktree, force: bool = False) -> None:
    if wt.is_main:
        raise GitError("cannot remove the main worktree")
    if wt.prunable:
        _git(repo, "worktree", "prune")
        return
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    _git(repo, *args, str(wt.path))


def delete_branch(repo: Path, branch: str) -> None:
    """Safe delete (``git branch -d``): refuses if the branch isn't merged."""
    _git(repo, "branch", "-d", branch)


def prune(repo: Path) -> None:
    _git(repo, "worktree", "prune")
