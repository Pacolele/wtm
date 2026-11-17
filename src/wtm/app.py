"""Textual TUI: repo list -> worktree list -> launch / manage."""

from __future__ import annotations

from pathlib import Path

import pyfiglet
from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Input, Label, ListItem, ListView, OptionList, Static
from textual.widgets.option_list import Option

from . import git, launch
from .config import Config, Repo, collapse_home

# Themes offered in the '?' menu. Names are Textual built-in themes; add more here.
THEMES = ["nord", "catppuccin-mocha", "catppuccin-latte", "catppuccin-frappe", "catppuccin-macchiato", "rose-pine"]

# Big-letter fonts tried in order until the repo name fits the terminal width.
BANNER_FONTS = ("ansi_shadow", "small")


def big_text(text: str, width: int) -> str:
    """Block-letter rendering of ``text`` that fits in ``width`` columns, or "" if none does."""
    for font in BANNER_FONTS:
        try:
            art = pyfiglet.figlet_format(text, font=font, width=10_000)
        except pyfiglet.FontNotFound:
            continue
        lines = [line.rstrip() for line in art.splitlines()]
        while lines and not lines[-1]:
            lines.pop()
        if lines and max(len(line) for line in lines) <= width:
            return "\n".join(lines)
    return ""


class Banner(Vertical):
    """Top area: breadcrumb, the selected repo's name in large letters, and a details line."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._name = ""
        self._crumb = ""
        self._meta = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="crumb")
        yield Static("", id="art", markup=False)
        yield Static("", id="meta")

    def show(self, name: str, crumb: str, meta: str) -> None:
        self._name, self._crumb, self._meta = name, crumb, meta
        self._draw()

    def on_resize(self) -> None:
        self._draw()

    def _draw(self) -> None:
        if not self.is_mounted:
            return
        width = max(self.size.width - 6, 20)  # minus horizontal padding
        art = big_text(self._name, width) if self._name else ""
        art_widget = self.query_one("#art", Static)
        # Fall back to a spaced-out bold title when no block font fits.
        art_widget.update(art or self._name.upper())
        art_widget.set_class(not art, "plain")
        self.query_one("#crumb", Static).update(self._crumb)
        self.query_one("#meta", Static).update(self._meta)


class Card(ListItem):
    """A tall, button-like list entry: bold title + status badge, with a detail line below."""

    def __init__(self, title: str, subtitle: str, badge: str = "") -> None:
        super().__init__()
        self._title = title
        self._subtitle = subtitle
        self._badge = badge  # Textual markup

    def compose(self) -> ComposeResult:
        with Horizontal(classes="card-top"):
            yield Label(self._title, classes="card-title", markup=False)
            yield Label(self._badge, classes="card-badge")
        yield Label(self._subtitle, classes="card-sub", markup=False)


class CardList(ListView):
    pass


def badge(text: str, color: str) -> str:
    return f"[${color}]{escape(text)}[/]"


def worktree_badge(wt: git.Worktree) -> str:
    if wt.prunable:
        return badge("✗ missing", "error")
    if wt.dirty:
        return badge("● " + wt.state, "warning")
    if wt.ahead or wt.behind:
        return badge("● " + wt.state, "accent")
    return badge("● clean", "success")


class SettingsScreen(ModalScreen[None]):
    """Opened with '?': pick a theme. Highlighting previews it; Enter saves it; Esc reverts."""

    CSS = """
    SettingsScreen { align: center middle; }
    #settings { width: 54; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #settings-title { text-style: bold; color: $accent; padding-bottom: 1; }
    #themes { height: auto; max-height: 14; border: none; background: $surface; }
    #settings-hint { color: $text-muted; padding-top: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Close"), Binding("question_mark", "cancel", "Close")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._original = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="settings"):
            yield Label("Settings  ·  Theme", id="settings-title")
            yield OptionList(*(Option(name, id=name) for name in THEMES), id="themes")
            yield Static("enter select   esc cancel", id="settings-hint")

    def on_mount(self) -> None:
        self._original = self.app.theme
        options = self.query_one(OptionList)
        if self._original in THEMES:
            options.highlighted = THEMES.index(self._original)
        options.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self.app.theme = str(event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.app.theme = str(event.option.id)
        self.config.set_theme(self.app.theme)
        self.config.save()
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.app.theme = self._original
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """Yes/no confirmation modal."""

    CSS = """
    ConfirmScreen { align: center middle; }
    #dialog { width: 60; height: auto; border: round $warning; padding: 1 2; background: $surface; }
    """
    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._message)
            yield Static("[b]y[/b] confirm   [b]n[/b]/[b]esc[/b] cancel")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class TextPromptScreen(ModalScreen[str | None]):
    """Single-line text input modal, e.g. for a new branch name."""

    CSS = """
    TextPromptScreen { align: center middle; }
    #dialog { width: 70; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, title: str, placeholder: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._title)
            yield Input(placeholder=self._placeholder, id="value")
            yield Static("[b]enter[/b] confirm   [b]esc[/b] cancel")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RepoFormScreen(ModalScreen[Repo | None]):
    """Add or edit a registered repo. Validates the path and name before closing."""

    CSS = """
    RepoFormScreen { align: center middle; }
    #repo-form { width: 74; height: auto; border: round $accent; padding: 1 2; background: $surface; }
    #repo-form-title { text-style: bold; color: $accent; padding-bottom: 1; }
    #repo-form Label.field { color: $text-muted; padding-top: 1; }
    #repo-form Input { border: none; height: 1; padding: 0 1; background: $boost; }
    #repo-form Input:focus { background: $primary 30%; }
    #repo-form-error { color: $error; padding-top: 1; }
    #repo-form-hint { color: $text-muted; padding-top: 1; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, config: Config, repo: Repo | None = None) -> None:
        super().__init__()
        self.config = config
        self.existing = repo

    def compose(self) -> ComposeResult:
        repo = self.existing
        agents_dir = Path.home() / ".kiro" / "agents"
        agents = sorted(p.stem for p in agents_dir.glob("*.json")) if agents_dir.is_dir() else []
        with Vertical(id="repo-form"):
            yield Label("Edit repo" if repo else "Add repo", id="repo-form-title")
            yield Label("Path to the repo's main checkout", classes="field")
            yield Input(value=collapse_home(repo.path) if repo else "", placeholder="~/projects/my-repo", id="f-path")
            yield Label("Name (blank = folder name)", classes="field")
            yield Input(value=repo.name if repo else "", placeholder="my-repo", id="f-name")
            yield Label("kiro-cli agent (blank = none)", classes="field")
            yield Input(value=repo.agent if repo else "", placeholder="myagent", id="f-agent")
            yield Static("", id="repo-form-error")
            hint = f"available agents: {', '.join(agents)}   " if agents else ""
            yield Static(f"{hint}tab next field   enter save   esc cancel", id="repo-form-hint")

    def on_mount(self) -> None:
        self.query_one("#f-path", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _fail(self, message: str) -> None:
        self.query_one("#repo-form-error", Static).update(message)

    def _submit(self) -> None:
        raw = self.query_one("#f-path", Input).value.strip()
        if not raw:
            return self._fail("Enter the path to a git repository.")
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            return self._fail(f"{path} is not a directory.")
        if not git.is_repo(path):
            return self._fail(f"{path} is not a git repository.")
        try:
            path = git.toplevel(path)  # a path inside a worktree resolves to the main checkout
        except git.GitError:
            pass
        name = self.query_one("#f-name", Input).value.strip() or path.name
        original = self.existing.name if self.existing else None
        if name != original and self.config.get(name) is not None:
            return self._fail(f"A repo named '{name}' is already registered.")
        agent = self.query_one("#f-agent", Input).value.strip()
        old = self.existing
        self.dismiss(
            Repo(
                name=name,
                path=path,
                agent=agent,
                command=old.command if old else "",
                worktree_root=old.worktree_root if old else "",
                extra=old.extra if old else {},
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class RepoScreen(Screen[None]):
    """Lists the repos registered in the wtm config (repo.json); the highlighted one is shown large in the banner."""

    BINDINGS = [
        Binding("enter", "open", "Open", priority=True),
        Binding("a", "add_repo", "Add repo"),
        Binding("e", "edit_repo", "Edit"),
        Binding("x", "remove_repo", "Remove"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self._repos: list[Repo] = []

    def compose(self) -> ComposeResult:
        yield Banner(id="banner")
        yield CardList(id="repos")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_cards()

    async def refresh_cards(self, select: str | None = None) -> None:
        cards = self.query_one(CardList)
        previous = cards.index or 0
        self._repos = sorted(self.config.repos, key=lambda r: r.name.lower())
        items = []
        for repo in self._repos:
            ok = repo.path.is_dir() and git.is_repo(repo.path)
            items.append(
                Card(
                    repo.name,
                    collapse_home(repo.path) + (f"   ·   agent: {repo.agent}" if repo.agent else ""),
                    badge("● ready", "success") if ok else badge("✗ missing", "error"),
                )
            )
        await cards.clear()
        await cards.extend(items)
        if items:
            names = [r.name for r in self._repos]
            cards.index = names.index(select) if select in names else min(previous, len(items) - 1)
            cards.focus()
        self.update_banner()

    def _highlighted(self) -> Repo | None:
        index = self.query_one(CardList).index
        return self._repos[index] if index is not None and index < len(self._repos) else None

    def update_banner(self) -> None:
        banner = self.query_one(Banner)
        repo = self._highlighted()
        if repo is None:
            banner.show("wtm", "worktree manager", "No repos registered yet. Press  a  to add one.")
            return
        meta = collapse_home(repo.path) + (f"    ·    agent: {repo.agent}" if repo.agent else "")
        banner.show(repo.name, "wtm  ▸  repos", meta)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self.update_banner()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Mouse click on a card."""
        self.action_open()

    async def action_refresh(self) -> None:
        await self.refresh_cards()

    def _save_repo(self, original: str | None, repo: Repo | None) -> None:
        if repo is None:
            return
        self.config.upsert(repo, original_name=original)
        self.config.save()
        self.notify(f"Saved '{repo.name}'")
        self.run_worker(self.refresh_cards(select=repo.name))

    def action_add_repo(self) -> None:
        self.app.push_screen(RepoFormScreen(self.config), lambda repo: self._save_repo(None, repo))

    def action_edit_repo(self) -> None:
        current = self._highlighted()
        if current is None:
            return
        self.app.push_screen(RepoFormScreen(self.config, current), lambda repo: self._save_repo(current.name, repo))

    @work
    async def action_remove_repo(self) -> None:
        current = self._highlighted()
        if current is None:
            return
        ok = await self.app.push_screen_wait(
            ConfirmScreen(
                f"Remove '{escape(current.name)}' from wtm?\n"
                "[dim]Only the entry is removed; no files or worktrees are touched.[/dim]"
            )
        )
        if not ok:
            return
        self.config.remove(current.name)
        self.config.save()
        await self.refresh_cards()

    def action_open(self) -> None:
        repo = self._highlighted()
        if repo is None:
            return
        if not (repo.path.is_dir() and git.is_repo(repo.path)):
            self.notify(f"{repo.path} is missing or not a git repo", severity="error")
            return
        self.app.push_screen(WorktreeScreen(self.config, repo))


class WorktreeScreen(Screen[None]):
    """Lists worktrees for one repo and launches the configured agent in the chosen one."""

    BINDINGS = [
        Binding("enter", "launch", "Launch", priority=True),
        Binding("t", "launch_tmux", "Launch in tmux"),
        Binding("n", "new_worktree", "New"),
        Binding("d", "delete_worktree", "Delete"),
        Binding("p", "prune", "Prune"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    def __init__(self, config: Config, repo: Repo) -> None:
        super().__init__()
        self.config = config
        self.repo = repo
        self._worktrees: list[git.Worktree] = []

    def compose(self) -> ComposeResult:
        yield Banner(id="banner")
        yield CardList(id="worktrees")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_cards()

    async def refresh_cards(self) -> None:
        cards = self.query_one(CardList)
        previous = cards.index or 0
        try:
            self._worktrees = git.list_worktrees(self.repo.path)
        except git.GitError as e:
            self.notify(str(e), severity="error")
            self._worktrees = []
        items = []
        for wt in self._worktrees:
            title = ("◆ " if wt.is_main else "  ") + wt.label
            subtitle = ("main worktree   ·   " if wt.is_main else "") + collapse_home(wt.path)
            items.append(Card(title, subtitle, worktree_badge(wt)))
        await cards.clear()
        await cards.extend(items)
        if items:
            cards.index = min(previous, len(items) - 1)
            cards.focus()
        count = len(self._worktrees)
        meta = collapse_home(self.repo.path)
        if self.repo.agent:
            meta += f"    ·    agent: {self.repo.agent}"
        meta += f"    ·    {count} worktree{'s' if count != 1 else ''}"
        self.query_one(Banner).show(self.repo.name, f"wtm  ▸  {self.repo.name}  ▸  worktrees", meta)

    def _selected(self) -> git.Worktree | None:
        index = self.query_one(CardList).index
        return self._worktrees[index] if index is not None and index < len(self._worktrees) else None

    async def action_refresh(self) -> None:
        await self.refresh_cards()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Mouse click on a card."""
        self.run_worker(self.action_launch())

    async def action_launch(self) -> None:
        wt = self._selected()
        if wt is None:
            return
        command = self.repo.launch_command(self.config.default_command)
        with self.app.suspend(), launch.renamed_tmux_window(wt.label), launch.agent_state_pipe():
            launch.run_here(command, wt.path)
        await self.refresh_cards()

    def action_launch_tmux(self) -> None:
        wt = self._selected()
        if wt is None:
            return
        if not launch.in_tmux():
            self.notify("Not inside tmux (or tmux not found)", severity="error")
            return
        command = self.repo.launch_command(self.config.default_command)
        try:
            launch.tmux_window(f"{self.repo.name}:{wt.label}", command, wt.path)
        except RuntimeError as e:
            self.notify(str(e), severity="error")
            return
        self.notify(f"Opened {wt.label} in a new tmux window")

    @work
    async def action_new_worktree(self) -> None:
        branch = await self.app.push_screen_wait(TextPromptScreen("New worktree: branch name", "feature/my-change"))
        if not branch:
            return
        dest = git.default_worktree_dir(self.repo.resolved_worktree_root, branch)
        try:
            description = git.add_worktree(self.repo.path, dest, branch)
        except git.GitError as e:
            self.notify(str(e), severity="error")
            return
        self.notify(f"{description} at {dest}")
        await self.refresh_cards()

    @work
    async def action_delete_worktree(self) -> None:
        wt = self._selected()
        if wt is None or wt.is_main:
            self.notify("Select a non-main worktree to delete", severity="warning")
            return
        ok = await self.app.push_screen_wait(ConfirmScreen(f"Remove worktree {wt.label} at {wt.path}?"))
        if not ok:
            return
        try:
            git.remove_worktree(self.repo.path, wt)
        except git.GitError as e:
            if "--force" not in str(e):
                self.notify(str(e), severity="error")
                await self.refresh_cards()
                return
            # git refuses when the worktree has modified/untracked files (or is locked).
            force = await self.app.push_screen_wait(
                ConfirmScreen(f"{escape(str(e))}\n\n[b]Force remove and discard those changes?[/b]")
            )
            if not force:
                return
            try:
                git.remove_worktree(self.repo.path, wt, force=True)
            except git.GitError as e2:
                self.notify(str(e2), severity="error")
                await self.refresh_cards()
                return
        if wt.branch:
            try:
                git.delete_branch(self.repo.path, wt.branch)
            except git.GitError as e:
                self.notify(f"Worktree removed; branch kept ({e})", severity="warning")
        await self.refresh_cards()

    async def action_prune(self) -> None:
        try:
            git.prune(self.repo.path)
        except git.GitError as e:
            self.notify(str(e), severity="error")
            return
        await self.refresh_cards()


class WtmApp(App[None]):
    TITLE = "wtm"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("question_mark", "settings", "Settings")]

    CSS = """
    Banner {
        height: auto;
        padding: 1 3;
        background: $panel;
        border-bottom: heavy $primary;
    }
    Banner #crumb { color: $text-muted; text-style: bold; }
    Banner #art { color: $primary; text-style: bold; height: auto; padding: 1 0 0 0; }
    Banner #art.plain { text-style: bold; padding: 1 0 0 0; }
    Banner #meta { color: $text-muted; padding: 1 0 0 0; }

    CardList { background: $background; padding: 1 2; height: 1fr; }
    Card {
        height: 4;
        padding: 1 2 0 2;
        margin: 0 0 1 0;
        background: $surface;
        border-left: thick $surface;
    }
    Card .card-top { height: 1; }
    Card .card-title { width: 1fr; text-style: bold; color: $text; }
    Card .card-badge { width: auto; }
    Card .card-sub { color: $text-muted; }
    CardList > Card:hover { background: $boost; }
    CardList > Card.-highlight,
    CardList:focus > Card.-highlight {
        background: $primary 25%;
        border-left: thick $primary;
    }
    """

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def on_mount(self) -> None:
        theme = self.config.theme
        if theme in self.available_themes:
            self.theme = theme
        self.push_screen(RepoScreen(self.config))

    def action_settings(self) -> None:
        # Ignore '?' while another modal (confirm, prompt, settings itself) is open.
        if not isinstance(self.screen, ModalScreen):
            self.push_screen(SettingsScreen(self.config))
