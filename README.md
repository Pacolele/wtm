# wtm

A terminal UI for managing git worktrees across several repos and starting a coding agent
(`kiro-cli chat` by default) inside the worktree you pick.

## Requirements

- Linux or macOS, with `git` (worktree support) on the PATH
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which installs Python 3.11+ and the
  dependencies (Textual and pyfiglet) on first run
- Optional: `tmux`, to open worktrees in their own windows
- Optional: `kiro-cli`, or any other command-line agent (see "Configuration")

## Install

```sh
git clone git@github.com:Pacolele/wtm.git ~/scripts/wtm
mkdir -p ~/.local/bin
ln -s ~/scripts/wtm/wtm ~/.local/bin/wtm     # make sure ~/.local/bin is on your PATH
wtm add myproject ~/projects/myproject       # register your first repo
wtm                                          # start the TUI
```

The launcher `wtm` runs `uv run --project <this folder> wtm`, so it works from any directory.
The first start creates `.venv` in the project folder.

## Using the TUI

`wtm` with no arguments opens two screens.

**Repo list.** Every registered repo, with its name shown as large banner text.

| Key | Action |
|-----|--------|
| `Enter` | Open the repo's worktrees |
| `a` / `e` / `x` | Add, edit or remove a repo |
| `r` | Refresh |
| `?` | Settings (theme picker) |
| `q` | Quit |

**Worktree list.** The worktrees of the selected repo, with branch and state (changes, prunable).

| Key | Action |
|-----|--------|
| `Enter` | Run the agent in the selected worktree, in the current terminal. wtm resumes when it exits |
| `t` | Run the agent in a new tmux window (only inside tmux) |
| `n` | New worktree: type a branch name |
| `d` | Delete the selected worktree (asks first, and offers a force remove if it has changes) |
| `p` | `git worktree prune` |
| `r` | Refresh |
| `q` | Back to the repo list |

How `n` picks the branch:

1. If the local branch exists, it is checked out.
2. Otherwise, if `origin/<branch>` exists, a local branch tracking it is created.
3. Otherwise, a new branch is created from the HEAD of the main worktree.

The worktree is created in `<worktree_root>/<branch>`, with `/` in the branch name replaced by `-`.
By default `worktree_root` is `<repo path>-wt`, next to the repo. After deleting a worktree, wtm
tries `git branch -d`, which keeps unmerged branches.

Inside tmux, wtm renames its window to the repo name while it runs and restores it afterwards.
Panes it opens report the agent's state (idle, working, done, blocked, error) in the tmux pane
option `@agent-state`, which you can show in your status bar. This works with agents that report their
state with the OSC 7501 terminal sequence, such as kiro-cli.

## Command line

| Command | What it does |
|---------|--------------|
| `wtm` | Start the TUI |
| `wtm list` | List registered repos |
| `wtm add NAME PATH [--agent AGENT] [--command CMD] [--worktree-root DIR]` | Register a repo, or update it if the name exists |
| `wtm remove NAME` | Unregister a repo (nothing is deleted on disk) |

`PATH` must be a git repository.

## Configuration

Everything is stored in one JSON file, `~/.config/wtm/repo.json`
(`$XDG_CONFIG_HOME/wtm/repo.json` when that is set). Set `WTM_CONFIG` to use another file.
The file is created the first time you add a repo. See `repo.json.example`:

```json
{
  "defaults": { "command": "kiro-cli chat" },
  "repos": {
    "myproject": {
      "path": "~/projects/myproject",
      "agent": "myagent",
      "command": "kiro-cli chat",
      "worktree_root": "~/projects/myproject-wt"
    }
  },
  "settings": { "theme": "catppuccin-macchiato" }
}
```

| Key | Meaning |
|-----|---------|
| `defaults.command` | Launch command for every repo. Default: `kiro-cli chat` |
| `repos.<name>.path` | Main checkout of the repo (required) |
| `repos.<name>.agent` | Appended to the command as `--agent NAME` |
| `repos.<name>.command` | Replaces `defaults.command` for this repo |
| `repos.<name>.worktree_root` | Where new worktrees go. Default: `<path>-wt` |
| `settings.theme` | Set from the `?` menu. One of `nord`, `catppuccin-mocha`, `catppuccin-latte`, `catppuccin-frappe`, `catppuccin-macchiato`, `rose-pine` |

Keys that wtm does not know are kept when it rewrites the file.

## Using another agent or tool

wtm is not tied to one service. The launch command is run through your shell inside the worktree,
so any command works:

```sh
wtm add api ~/projects/api --command "claude"            # a different agent for one repo
wtm add web ~/projects/web --command "nvim ."            # an editor
wtm add ops ~/projects/ops --command "$SHELL"            # just a shell in the worktree
```

Set `defaults.command` to change the command for all repos. The `--agent` flag is appended as
`--agent NAME`, so leave `agent` empty for commands that do not accept it.

Services are limited to git (worktrees are handled with the `git` command) and an optional tmux.
There are no plugins.
