from __future__ import annotations

import json
import os
import pty
import shlex
import signal
import subprocess
import sys
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

# Textual's enhanced Kitty keyboard protocol reports physical key presses in
# supporting terminals. That prevents macOS input methods (including Vietnamese
# Telex) from composing text before it reaches the Input widget. Users who need
# the enhanced protocol can explicitly restore it with
# TEXTUAL_DISABLE_KITTY_KEY=0.
os.environ.setdefault("TEXTUAL_DISABLE_KITTY_KEY", "1")

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    RichLog,
    Static,
)

from ankii.settings import LanguageProfile, Settings, load_settings


@dataclass(frozen=True)
class TuiAction:
    name: str
    key: str
    label: str
    command: tuple[str, ...]
    description: str
    needs_settings: bool = True
    vietnamese_only: bool = False
    section: str = "New"


ACTIONS: tuple[TuiAction, ...] = (
    TuiAction("add", "a", "Add a word", ("add",), "Create a vocabulary card in the inbox."),
    TuiAction(
        "new",
        "2",
        "Create from word list",
        ("new",),
        "Paste a target-language, native-language, or mixed list and create a review.",
    ),
    TuiAction(
        "analyze",
        "n",
        "Analyze text",
        ("analyze",),
        "Analyze a passage and choose vocabulary or grammar cards.",
    ),
    TuiAction(
        "wizard",
        "w",
        "YourHomework wizard",
        ("yhw", "wizard"),
        "Fetch, review, tag, approve, and import a public lesson.",
        vietnamese_only=True,
    ),
    TuiAction(
        "tag",
        "t",
        "Tag a review",
        ("tag",),
        "Choose a review and add AI-generated taxonomy tags.",
        section="Review",
    ),
    TuiAction(
        "approve",
        "r",
        "Review and approve",
        ("approve",),
        "Open an existing review and approve or edit its cards.",
        section="Review",
    ),
    TuiAction(
        "import",
        "i",
        "Import approved cards",
        ("import",),
        "Choose a review, preview duplicates, and import it into Anki.",
        section="Import",
    ),
    TuiAction(
        "reimport",
        "j",
        "Reimport local reviews",
        ("reimport", "--all"),
        "Preview and update existing Anki notes from local review files.",
        section="Import",
    ),
    TuiAction(
        "backfill-examples",
        "b",
        "Backfill examples",
        ("backfill-examples",),
        "Fill empty example fields on existing Vocabulary notes from a review.",
        section="Maintenance",
    ),
    TuiAction(
        "backfill-audio",
        "e",
        "Generate missing audio",
        ("backfill-audio",),
        "Review missing Vocabulary audio and generate selected clips.",
        section="Maintenance",
    ),
    TuiAction(
        "retag",
        "g",
        "Retag Vocabulary notes",
        ("retag", "--all"),
        "Preview and recalculate taxonomy tags on Vocabulary notes.",
        section="Maintenance",
    ),
    TuiAction(
        "connection",
        "c",
        "Check Anki connection",
        ("anki", "check"),
        "Confirm that Anki Desktop and AnkiConnect are available.",
        section="Anki",
    ),
    TuiAction(
        "anki-profile-data",
        "1",
        "List current profile data",
        ("anki", "list"),
        "Inspect the active profile deck, notes, cards, fields, and card types.",
        section="Anki",
    ),
    TuiAction(
        "anki-update",
        "u",
        "Update Anki settings",
        ("anki", "update"),
        "Enforce managed note types and provision the active profile deck.",
        section="Anki",
    ),
    TuiAction(
        "profile-languages",
        "4",
        "List supported languages",
        ("profile", "languages"),
        "Show languages accepted when creating a profile.",
        needs_settings=False,
        section="Profiles",
    ),
    TuiAction(
        "profile-create",
        "o",
        "Create a profile",
        ("profile", "create"),
        "Create a language profile and its private review directory.",
        section="Profiles",
    ),
    TuiAction(
        "profile-default",
        "d",
        "Set default profile",
        ("profile", "default"),
        "Choose which profile is used when no profile is specified.",
        section="Profiles",
    ),
    TuiAction(
        "profile-list",
        "l",
        "List profiles",
        ("profile", "list"),
        "Show every configured profile and the current default.",
        section="Profiles",
    ),
    TuiAction(
        "profile-delete",
        "x",
        "Delete a profile",
        ("profile", "delete"),
        "Remove a profile configuration while preserving its review files.",
        section="Profiles",
    ),
    TuiAction(
        "audio-setup",
        "7",
        "Set up audio generation",
        ("audio", "setup"),
        "Choose OpenAI or a local device voice for this profile.",
        section="Profiles",
    ),
    TuiAction(
        "audio-voices",
        "8",
        "List local audio voices",
        ("audio", "voices"),
        "List speech voices and language locales installed on this device.",
        needs_settings=False,
        section="Profiles",
    ),
    TuiAction(
        "version",
        "v",
        "Check for updates",
        ("version",),
        "Compare the installed ankii version with the latest version on GitHub.",
        needs_settings=False,
        section="Application",
    ),
    TuiAction(
        "upgrade",
        "z",
        "Upgrade ankii",
        ("upgrade",),
        "Upgrade the pipx installation to the latest available ankii version.",
        needs_settings=False,
        section="Application",
    ),
    TuiAction(
        "key-status",
        "k",
        "Check OpenAI key",
        ("key", "status"),
        "Check whether an OpenAI API key is available.",
        needs_settings=False,
        section="Application",
    ),
    TuiAction(
        "key-set",
        "5",
        "Set OpenAI key",
        ("key", "set"),
        "Securely add or replace the OpenAI API key.",
        needs_settings=False,
        section="Application",
    ),
    TuiAction(
        "key-delete",
        "6",
        "Delete OpenAI key",
        ("key", "delete"),
        "Delete the stored OpenAI API key from Keychain.",
        needs_settings=False,
        section="Application",
    ),
    TuiAction(
        "setup",
        "s",
        "First-time setup",
        ("setup",),
        "Create local settings and optionally store an OpenAI API key.",
        needs_settings=False,
        section="Application",
    ),
)


def _action_items() -> list[ListItem]:
    items: list[ListItem] = []
    current_section: str | None = None
    for action in ACTIONS:
        if action.section != current_section:
            current_section = action.section
            items.append(
                ListItem(
                    Label(action.section),
                    classes="action-section",
                    disabled=True,
                )
            )
        items.append(
            ListItem(
                Label(f"{action.key}   {action.label}"),
                id=f"action-{action.name}",
            )
        )
    return items


def command_argv(
    settings_path: Path,
    profile_name: str | None,
    action: TuiAction,
) -> list[str]:
    """Build a command that re-enters the existing CLI without shell parsing."""
    argv = [sys.executable, "-m", "ankii.cli", "--settings", str(settings_path)]
    if profile_name and action.needs_settings:
        argv.extend(("--profile", profile_name))
    argv.extend(action.command)
    return argv


def _inbox_counts(profile: LanguageProfile) -> tuple[int, int]:
    if not profile.inbox_path.exists():
        return 0, 0
    try:
        data = json.loads(profile.inbox_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0, 0
    cards = data.get("cards", []) if isinstance(data, dict) else []
    if not isinstance(cards, list):
        return 0, 0
    approved = sum(isinstance(card, dict) and bool(card.get("approved")) for card in cards)
    return len(cards), approved


class CommandPane(Vertical):
    """Run an existing interactive CLI command inside the Textual application."""

    DEFAULT_CSS = """
    CommandPane {
        height: 1fr;
        display: none;
        background: #111418;
    }

    #command-header {
        height: auto;
        padding: 1 2;
        background: #202631;
        color: #ffd166;
        text-style: bold;
    }

    #terminal-frame {
        height: 1fr;
        margin: 1 2;
        border: round #3a86ff;
        background: #0b0e11;
    }

    #terminal-output {
        height: 1fr;
        padding: 1 2;
        background: #0b0e11;
        color: #e8edf2;
        scrollbar-color: #3a86ff;
    }

    #terminal-input {
        dock: bottom;
        margin: 0 2 1 2;
        border: tall #3a86ff;
        background: #171b21;
    }

    #command-footer {
        height: auto;
        padding: 0 2 1 2;
    }

    #command-status {
        width: 1fr;
        padding: 1 0;
        color: #9aa7b2;
    }

    #command-back {
        width: auto;
        min-width: 18;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Cancel command", priority=True),
        Binding("escape", "close", "Back", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__(id="command-pane")
        self.display = False
        self.command_title = ""
        self.argv: list[str] = []
        self.process: subprocess.Popen[bytes] | None = None
        self.master_fd: int | None = None
        self.return_code: int | None = None

    def compose(self) -> ComposeResult:
        yield Static(self.command_title, id="command-header")
        with VerticalScroll(id="terminal-frame"):
            yield RichLog(id="terminal-output", wrap=True, markup=False, auto_scroll=True)
        yield Input(placeholder="Type a response and press Enter", id="terminal-input")
        with Horizontal(id="command-footer"):
            yield Static("Command running · Ctrl+C cancels", id="command-status")
            yield Button("Cancel", id="command-back", variant="error")

    def start(self, title: str, argv: list[str]) -> None:
        self.command_title = title
        self.argv = argv
        self.return_code = None
        self.query_one("#command-header", Static).update(title)
        output = self.query_one("#terminal-output", RichLog)
        output.clear()
        input_widget = self.query_one("#terminal-input", Input)
        input_widget.disabled = False
        input_widget.value = ""
        self.query_one("#command-status", Static).update("Command running · Ctrl+C cancels")
        button = self.query_one("#command-back", Button)
        button.label = "Cancel"
        button.variant = "error"
        try:
            command = ["ankii", *self.argv[self.argv.index("--settings") + 2 :]]
        except ValueError:
            command = self.argv
        output.write(f"$ {shlex.join(command)}\n")
        try:
            master_fd, slave_fd = pty.openpty()
            environment = os.environ.copy()
            environment.update({"PYTHONUNBUFFERED": "1", "TERM": "dumb", "NO_COLOR": "1"})
            self.process = subprocess.Popen(
                self.argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=environment,
                close_fds=True,
                start_new_session=True,
            )
            os.close(slave_fd)
            self.master_fd = master_fd
        except OSError as exc:
            output.write(f"Unable to start command: {exc}")
            self._finish(1)
            return
        threading.Thread(target=self._read_output, daemon=True).start()
        input_widget.focus()

    def _read_output(self) -> None:
        assert self.master_fd is not None
        assert self.process is not None
        try:
            while True:
                try:
                    chunk = os.read(self.master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
                try:
                    self.app.call_from_thread(self._append_output, text)
                except RuntimeError:
                    return
        finally:
            return_code = self.process.wait()
            with suppress(OSError):
                os.close(self.master_fd)
            self.master_fd = None
            with suppress(RuntimeError):
                self.app.call_from_thread(self._finish, return_code)

    def _append_output(self, text: str) -> None:
        self.query_one("#terminal-output", RichLog).write(text)

    @on(Input.Submitted, "#terminal-input")
    def submit_input(self, event: Input.Submitted) -> None:
        if self.master_fd is None or self.return_code is not None:
            return
        try:
            os.write(self.master_fd, (event.value + "\n").encode())
        except OSError:
            return
        event.input.value = ""

    @on(Button.Pressed, "#command-back")
    def press_back(self) -> None:
        if self.return_code is None:
            self.action_interrupt()
        else:
            self.action_close()

    def action_interrupt(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGINT)
            self.query_one("#command-status", Static).update("Cancelling command…")
        except (OSError, ProcessLookupError):
            pass

    def action_close(self) -> None:
        if self.return_code is None:
            self.action_interrupt()
            return
        self.app.close_command()

    def _finish(self, return_code: int) -> None:
        self.return_code = return_code
        input_widget = self.query_one("#terminal-input", Input)
        input_widget.disabled = True
        status = self.query_one("#command-status", Static)
        if return_code == 0:
            status.update("Command finished successfully · Esc returns to dashboard")
        elif return_code == 130:
            status.update("Command cancelled · Esc returns to dashboard")
        else:
            status.update(f"Command exited with status {return_code} · Esc returns to dashboard")
        button = self.query_one("#command-back", Button)
        button.label = "Back to dashboard"
        button.variant = "primary"
        button.focus()

    def on_unmount(self) -> None:
        if self.process is not None and self.process.poll() is None:
            with suppress(OSError):
                os.killpg(self.process.pid, signal.SIGTERM)


class AnkiiApp(App[None]):
    TITLE = "ankii"
    SUB_TITLE = "Anki study workflow"

    CSS = """
    Screen {
        background: #111418;
        color: #e8edf2;
    }

    #body {
        height: 1fr;
    }

    #sidebar {
        width: 38;
        min-width: 30;
        border-right: solid #3a86ff;
        background: #171b21;
    }

    #profile {
        height: auto;
        padding: 1 2;
        background: #202631;
        color: #8ecae6;
    }

    #actions {
        height: 1fr;
        background: #171b21;
    }

    ListItem {
        padding: 0 1;
    }

    ListItem.action-section {
        height: 2;
        padding: 1 1 0 1;
        color: #8ecae6;
        text-style: bold;
        background: #171b21;
    }

    ListItem.--highlight {
        background: #3a86ff;
        color: white;
    }

    #main {
        width: 1fr;
        padding: 2 3;
    }

    #welcome {
        color: #ffd166;
        text-style: bold;
        margin-bottom: 1;
    }

    #details {
        height: auto;
        min-height: 7;
        border: round #3a86ff;
        padding: 1 2;
        margin-bottom: 1;
    }

    #summary {
        height: auto;
        border: round #495361;
        padding: 1 2;
    }

    #hint {
        dock: bottom;
        height: auto;
        padding-top: 1;
        color: #9aa7b2;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        *(Binding(action.key, f"run_action('{action.name}')", action.label) for action in ACTIONS),
        Binding("p", "next_profile", "Profile"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, settings_path: Path, requested_profile: str | None = None) -> None:
        super().__init__()
        self.settings_path = settings_path.expanduser()
        self.requested_profile = requested_profile
        self.follow_default_profile = requested_profile is None
        self.settings: Settings | None = None
        self.profile: LanguageProfile | None = None
        self.config_error: str | None = None
        self._reload_settings()

    def _reload_settings(self) -> None:
        try:
            self.settings = load_settings(self.settings_path)
            selected = None if self.follow_default_profile else self.requested_profile
            self.profile = self.settings.select_profile(selected)
            if not self.follow_default_profile:
                self.requested_profile = self.profile.name
            self.config_error = None
        except (OSError, TypeError, ValueError) as exc:
            self.settings = None
            self.profile = None
            self.config_error = str(exc)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                yield Static(self._profile_text(), id="profile")
                yield ListView(*_action_items(), id="actions")
            with Vertical(id="main"):
                yield Static("One terminal for your complete Anki workflow", id="welcome")
                yield Static(ACTIONS[0].description, id="details")
                yield Static(self._summary_text(), id="summary")
                yield Static(
                    "Select an action with ↑/↓ and Enter, or use its shortcut key. "
                    "Commands open in an interactive console inside ankii.",
                    id="hint",
                )
        yield CommandPane()
        yield Footer()

    def _profile_text(self) -> str:
        if self.profile is None:
            return "Profile: not configured\nPress s for First-time setup"
        return (
            f"Profile: {self.profile.name}\n"
            f"{self.profile.study_language} → {self.profile.native_language}"
        )

    def _summary_text(self) -> str:
        if self.profile is None:
            return f"Configuration\n\n{self.config_error or 'Settings are unavailable.'}"
        total, approved = _inbox_counts(self.profile)
        pending = total - approved
        return (
            "Current profile\n\n"
            f"Deck:       {self.profile.deck}\n"
            f"Inbox:      {total} cards\n"
            f"Approved:   {approved}\n"
            f"Unapproved: {pending}\n"
            f"Reviews:    {self.profile.review_root}"
        )

    def _refresh_dashboard(self) -> None:
        self._reload_settings()
        self.query_one("#profile", Static).update(self._profile_text())
        self.query_one("#summary", Static).update(self._summary_text())

    @on(ListView.Highlighted, "#actions")
    def show_action_details(self, event: ListView.Highlighted) -> None:
        if event.item is None or event.item.id is None:
            return
        action = self._find_action(event.item.id.removeprefix("action-"))
        self.query_one("#details", Static).update(
            f"{action.label}\n\n{action.description}\n\nCommand: ankii {' '.join(action.command)}"
        )

    @on(ListView.Selected, "#actions")
    def select_action(self, event: ListView.Selected) -> None:
        if event.item.id is not None:
            self.action_run_action(event.item.id.removeprefix("action-"))

    def action_run_action(self, name: str) -> None:
        action = self._find_action(name)
        if action.needs_settings and self.profile is None:
            self.notify("Run first-time setup before using this action.", severity="warning")
            return
        if action.vietnamese_only and self.profile is not None and not self.profile.is_vietnamese:
            self.notify("This action requires a Vietnamese profile.", severity="warning")
            return
        argv = command_argv(
            self.settings_path,
            (
                self.profile.name
                if self.profile is not None and not self.follow_default_profile
                else None
            ),
            action,
        )
        self.query_one("#body").display = False
        command_pane = self.query_one(CommandPane)
        command_pane.display = True
        command_pane.start(action.label, argv)

    def close_command(self) -> None:
        self.query_one(CommandPane).display = False
        self.query_one("#body").display = True
        self._refresh_dashboard()
        actions = self.query_one("#actions", ListView)
        self.call_after_refresh(actions.focus)

    def action_next_profile(self) -> None:
        if self.settings is None or not self.settings.profiles:
            self.notify("Run first-time setup before selecting a profile.", severity="warning")
            return
        names = list(self.settings.profiles)
        current = self.profile.name if self.profile is not None else names[0]
        next_index = (names.index(current) + 1) % len(names)
        self.follow_default_profile = False
        self.requested_profile = names[next_index]
        self._refresh_dashboard()
        self.notify(f"Active profile: {self.requested_profile}")

    @staticmethod
    def _find_action(name: str) -> TuiAction:
        return next(action for action in ACTIONS if action.name == name)


def run_tui(settings_path: Path, profile_name: str | None = None) -> int:
    AnkiiApp(settings_path, profile_name).run()
    return 0
