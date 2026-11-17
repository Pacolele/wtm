"""Mirror a coding agent's OSC 7501 program status into the tmux pane option ``@agent-state``.

kiro-cli reports its state on the terminal, e.g. ``ESC ] 7501 ; state=blocked:kind=permission:app=kiro-cli BEL``
while it waits for a tool approval. tmux 3.8 discards OSC 7501 (tmux/tmux#5713), so wtm copies the pane's
output to this script with ``pipe-pane -O``. Each change of the root record's state is written to the pane
as ``@agent-state`` (idle, working, done, blocked or error); the option is removed when the pipe closes.
This module only reports state; the tmux status-bar formats decide how to show it.

Spec: https://gist.github.com/mitchellh/7acae3abd8355c1c00287d67e96c913a

Runs as a standalone script (``python -I agentstate.py``), so it must only import the standard library.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections.abc import Callable

OPTION = "@agent-state"
STATES = frozenset({"idle", "working", "done", "blocked", "error"})

_START = b"\x1b]7501;"
_MAX_REPORT = 4096  # the spec's cap on one whole report
# OSC 7501 ; body ST, where ST is BEL or ESC \ (kiro-cli uses BEL).
_REPORT = re.compile(rb"\x1b\]7501;([^\x07\x1b]{0,%d})(?:\x07|\x1b\\)" % _MAX_REPORT)


def root_state(body: bytes) -> str | None:
    """State a report body gives the root record: a state name, "" for a clear, or None if it doesn't apply."""
    pairs: dict[bytes, bytes] = {}
    for pair in body.split(b":"):
        key, sep, value = pair.partition(b"=")
        if sep:
            pairs[key.strip()] = value.strip()
    if b"id" in pairs:  # child records (e.g. subagents) don't change the pane's own state
        return None
    state = pairs.get(b"state", b"").decode("ascii", "replace")
    if state == "clear":
        return ""
    return state if state in STATES else None


def watch(fd: int, set_state: Callable[[str], None]) -> None:
    """Read terminal output from ``fd`` until EOF; call ``set_state`` on each change ("" = no state)."""
    current = ""
    pending = b""
    while chunk := os.read(fd, 65536):
        data = pending + chunk
        end = 0
        for match in _REPORT.finditer(data):
            end = match.end()
            state = root_state(match.group(1))
            if state is not None and state != current:
                current = state
                set_state(state)
        rest = data[end:]
        start = rest.rfind(_START)
        if start != -1 and len(rest) - start <= len(_START) + _MAX_REPORT + 2:
            pending = rest[start:]  # a report whose terminator hasn't arrived yet
        else:
            pending = rest[-(len(_START) - 1) :]  # the start marker itself may be split across reads
    if current:
        set_state("")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Copy OSC 7501 status from stdin into a tmux pane option.")
    parser.add_argument("--socket", required=True, help="tmux server socket, #{socket_path}")
    parser.add_argument("--pane", required=True, help="pane to label, #{pane_id}")
    parser.add_argument("--tmux", default="tmux", help="tmux binary (pipe-pane runs with the server's PATH)")
    args = parser.parse_args(argv)

    def set_state(state: str) -> None:
        cmd = [args.tmux, "-S", args.socket, "set-option", "-p", "-t", args.pane]
        cmd += [OPTION, state] if state else ["-u", OPTION]
        try:
            subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass  # tmux missing or gone; keep draining the pipe so the pane never blocks

    watch(0, set_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
