"""wtm entry point: launches the TUI, or handles `add`/`remove`/`list` repo-registry subcommands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import git
from .config import Config, Repo


def cmd_list(config: Config) -> int:
    repos = sorted(config.repos, key=lambda r: r.name.lower())
    if not repos:
        print(f"No repos registered. Add one with: wtm add <name> <path> [--agent AGENT]\n({config.path})")
        return 0
    for r in repos:
        bits = [f"{r.name:<20} {r.path}"]
        if r.agent:
            bits.append(f"agent={r.agent}")
        if r.command:
            bits.append(f"command={r.command!r}")
        if r.editor:
            bits.append(f"editor={r.editor!r}")
        print("  ".join(bits))
    return 0


def cmd_add(config: Config, args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if not git.is_repo(path):
        print(f"wtm: {path} is not a git repository", file=sys.stderr)
        return 1
    existing = config.get(args.name)
    repo = Repo(
        name=args.name,
        path=path,
        agent=args.agent or (existing.agent if existing else ""),
        command=args.command or (existing.command if existing else ""),
        editor=args.editor or (existing.editor if existing else ""),
        worktree_root=args.worktree_root or (existing.worktree_root if existing else ""),
        extra=existing.extra if existing else {},
    )
    config.upsert(repo)
    config.save()
    print(f"Registered '{repo.name}' -> {repo.path}" + (f" (agent={repo.agent})" if repo.agent else ""))
    return 0


def cmd_remove(config: Config, args: argparse.Namespace) -> int:
    if not config.remove(args.name):
        print(f"wtm: no repo named '{args.name}'", file=sys.stderr)
        return 1
    config.save()
    print(f"Removed '{args.name}'")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wtm", description="Manage git worktrees across repos.")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List registered repos")

    p_add = sub.add_parser("add", help="Register a repo")
    p_add.add_argument("name", help="Short name to select it by in the TUI")
    p_add.add_argument("path", help="Path to the repo's main checkout")
    p_add.add_argument("--agent", default="", help="kiro-cli agent profile to launch with (--agent NAME)")
    p_add.add_argument("--command", default="", help="Override the launch command (default: kiro-cli chat)")
    p_add.add_argument("--editor", default="", help="Editor to open worktrees with (default: $VISUAL, $EDITOR, vi)")
    p_add.add_argument("--worktree-root", default="", help="Where new worktrees are created (default: <path>-wt)")

    p_remove = sub.add_parser("remove", help="Unregister a repo")
    p_remove.add_argument("name")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = Config.load()

    if args.cmd == "list":
        return cmd_list(config)
    if args.cmd == "add":
        return cmd_add(config, args)
    if args.cmd == "remove":
        return cmd_remove(config, args)

    from .app import WtmApp

    WtmApp(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
