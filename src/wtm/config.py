"""Central settings, stored in ``~/.config/wtm/repo.json`` (``$XDG_CONFIG_HOME/wtm/repo.json`` when set).

Override the location with the ``WTM_CONFIG`` environment variable.

Format::

    {
      "defaults": {"command": "kiro-cli chat"},
      "settings": {"theme": "nord"},          # set from the '?' menu in the TUI
      "repos": {
        "myproject": {
          "path": "~/projects/myproject",
          "agent": "myagent",                       # optional: appended as `--agent myagent`
          "command": "kiro-cli chat",             # optional: overrides defaults.command
          "worktree_root": "~/projects/myproject-wt"  # optional: default "<repo parent>/<name>-wt"
        }
      }
    }

Keys wtm doesn't know about are preserved when it rewrites the file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BUILTIN_COMMAND = "kiro-cli chat"
_KNOWN = ("path", "agent", "command", "worktree_root")


def config_path() -> Path:
    override = os.environ.get("WTM_CONFIG")
    if override:
        return Path(override).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser()
    return base / "wtm" / "repo.json"


def collapse_home(path: Path) -> str:
    """Store paths as ``~/...`` where possible so the file stays readable and portable."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


@dataclass
class Repo:
    name: str
    path: Path
    agent: str = ""
    command: str = ""
    worktree_root: str = ""
    extra: dict[str, Any] = field(default_factory=dict)  # unknown keys, round-tripped untouched

    def launch_command(self, default: str) -> str:
        """Shell command line that starts the coding agent for this repo."""
        cmd = self.command or default
        return f"{cmd} --agent {self.agent}" if self.agent else cmd

    @property
    def resolved_worktree_root(self) -> Path:
        if self.worktree_root:
            return Path(self.worktree_root).expanduser()
        return self.path.parent / f"{self.path.name}-wt"


class Config:
    def __init__(self, data: dict[str, Any], path: Path):
        self.data = data
        self.path = path

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or config_path()
        if not path.exists():
            return cls({}, path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"wtm: cannot parse {path}: {e}") from e
        if not isinstance(data, dict):
            raise SystemExit(f"wtm: {path} must contain a JSON object")
        return cls(data, path)

    @property
    def default_command(self) -> str:
        return (self.data.get("defaults") or {}).get("command") or BUILTIN_COMMAND

    @property
    def theme(self) -> str:
        return (self.data.get("settings") or {}).get("theme") or ""

    def set_theme(self, name: str) -> None:
        self.data.setdefault("settings", {})["theme"] = name

    @property
    def repos(self) -> list[Repo]:
        result: list[Repo] = []
        for name, entry in (self.data.get("repos") or {}).items():
            if not isinstance(entry, dict) or "path" not in entry:
                raise SystemExit(f"wtm: repo '{name}' in {self.path} needs a \"path\"")
            result.append(
                Repo(
                    name=name,
                    path=Path(entry["path"]).expanduser(),
                    agent=entry.get("agent", ""),
                    command=entry.get("command", ""),
                    worktree_root=entry.get("worktree_root", ""),
                    extra={k: v for k, v in entry.items() if k not in _KNOWN},
                )
            )
        return result

    def get(self, name: str) -> Repo | None:
        return next((r for r in self.repos if r.name == name), None)

    def upsert(self, repo: Repo, original_name: str | None = None) -> None:
        """Insert or replace a repo; pass ``original_name`` when renaming."""
        repos = self.data.setdefault("repos", {})
        if original_name and original_name != repo.name:
            repos.pop(original_name, None)
        entry: dict[str, Any] = {"path": collapse_home(repo.path)}
        for key in ("agent", "command", "worktree_root"):
            value = getattr(repo, key)
            if value:
                entry[key] = value
        entry.update(repo.extra)
        repos[repo.name] = entry

    def remove(self, name: str) -> bool:
        repos = self.data.get("repos") or {}
        if name not in repos:
            return False
        del repos[name]
        return True

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)
