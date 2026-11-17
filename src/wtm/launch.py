"""Starting the coding agent (or a shell) inside a worktree."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .agentstate import OPTION as AGENT_STATE_OPTION

_AGENT_STATE_SCRIPT = Path(__file__).with_name("agentstate.py")


def in_tmux() -> bool:
    return bool(os.environ.get("TMUX")) and shutil.which("tmux") is not None


def run_here(command: str, cwd: Path) -> int:
    """Run ``command`` in the current terminal, blocking until it exits."""
    return subprocess.run(command, shell=True, cwd=cwd).returncode


def shell_command() -> str:
    return os.environ.get("SHELL") or "/bin/sh"


def _tmux(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tmux", *args], capture_output=True, text=True)


def _tmux_literal(text: str) -> str:
    """tmux expands formats in window names (``#S`` becomes the session name); ``##`` is a literal ``#``."""
    return text.replace("#", "##")


def _agent_state_pipe() -> str:
    """``pipe-pane`` command that copies the pane's agent status into the pane option ``@agent-state``.

    tmux expands formats (``#``) and strftime (``%``) in this command, so the literal part is escaped.
    """
    parts = [sys.executable, "-I", str(_AGENT_STATE_SCRIPT), "--tmux", shutil.which("tmux") or "tmux"]
    literal = " ".join(shlex.quote(p) for p in parts).replace("#", "##").replace("%", "%%")
    return f"{literal} --socket #{{q:socket_path}} --pane #{{pane_id}}"


def tmux_window(name: str, command: str, cwd: Path) -> None:
    """Open ``command`` in a new tmux window so several worktrees can run side by side.

    The new pane also gets the agent-state pipe (best effort; the window works without it).
    """
    proc = subprocess.run(
        ["tmux", "new-window", "-P", "-F", "#{pane_id}", "-n", _tmux_literal(name), "-c", str(cwd), command],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tmux new-window failed")
    pane = proc.stdout.strip()
    if pane:
        _tmux("pipe-pane", "-O", "-t", pane, _agent_state_pipe())


@contextmanager
def agent_state_pipe() -> Iterator[None]:
    """Inside tmux, copy the agent status of wtm's own pane into ``@agent-state`` while the block runs.

    Skipped when the pane already has a pipe (``pipe-pane`` would replace it) or tmux can't be queried.
    """
    pane = os.environ.get("TMUX_PANE")
    if not (in_tmux() and pane):
        yield
        return
    piped = _tmux("display-message", "-p", "-t", pane, "#{pane_pipe}")
    if piped.returncode != 0 or piped.stdout.strip() != "0":
        yield
        return
    _tmux("pipe-pane", "-O", "-t", pane, _agent_state_pipe())
    try:
        yield
    finally:
        _tmux("pipe-pane", "-t", pane)  # no command closes the pipe; the watcher also clears the option on EOF
        _tmux("set-option", "-p", "-u", "-t", pane, AGENT_STATE_OPTION)


@contextmanager
def renamed_tmux_window(name: str) -> Iterator[None]:
    """Inside tmux, name the window wtm runs in ``name`` while the block runs, then restore the old name.

    Best effort: if tmux can't be queried, the block still runs, just without the rename.
    """
    if not in_tmux():
        yield
        return
    # Target wtm's own pane so the right window is renamed even when another window is focused.
    target = ["-t", os.environ["TMUX_PANE"]] if os.environ.get("TMUX_PANE") else []
    old_name = _tmux("display-message", "-p", *target, "#{window_name}")
    # Window-local value only; empty means the window follows the global setting (on by default).
    old_auto = _tmux("show-options", "-wqv", *target, "automatic-rename")
    if old_name.returncode != 0 or old_auto.returncode != 0:
        yield
        return
    _tmux("rename-window", *target, _tmux_literal(name))  # also turns automatic-rename off
    try:
        yield
    finally:
        _tmux("rename-window", *target, _tmux_literal(old_name.stdout.rstrip("\n")))
        auto = old_auto.stdout.strip()
        if auto:
            _tmux("set-option", "-w", *target, "automatic-rename", auto)
        else:
            _tmux("set-option", "-wu", *target, "automatic-rename")
