import asyncio
import os
from pathlib import Path

from ankii import cli
from ankii.settings import create_default_settings, set_default_profile
from ankii.tui import ACTIONS, AnkiiApp, CommandPane, command_argv


def test_tui_preserves_terminal_input_method_composition() -> None:
    assert os.environ["TEXTUAL_DISABLE_KITTY_KEY"] == "1"


def test_dashboard_hides_command_pane_on_startup(tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")
    app = AnkiiApp(settings_path)

    async def check_layout() -> None:
        async with app.run_test():
            assert app.query_one("#body").display
            assert not app.query_one(CommandPane).display

    asyncio.run(check_layout())


def test_command_argv_preserves_settings_and_profile() -> None:
    action = next(action for action in ACTIONS if action.name == "add")

    argv = command_argv(Path("/tmp/anki.toml"), "french", action)

    assert argv[-5:] == ["--settings", "/tmp/anki.toml", "--profile", "french", "add"]


def test_setup_command_does_not_pass_profile() -> None:
    action = next(action for action in ACTIONS if action.name == "setup")

    argv = command_argv(Path("/tmp/anki.toml"), "french", action)

    assert argv[-3:] == ["--settings", "/tmp/anki.toml", "setup"]


def test_profile_management_actions_are_available() -> None:
    commands = {action.name: action.command for action in ACTIONS}

    assert commands["profile-create"] == ("profile", "create")
    assert commands["profile-default"] == ("profile", "default")
    assert commands["profile-list"] == ("profile", "list")
    assert commands["profile-delete"] == ("profile", "delete")


def test_dashboard_contains_every_cli_leaf_command() -> None:
    commands = {action.command for action in ACTIONS}

    assert commands == {
        ("version",),
        ("upgrade",),
        ("setup",),
        ("profile", "languages"),
        ("profile", "list"),
        ("profile", "create"),
        ("profile", "default"),
        ("profile", "delete"),
        ("add",),
        ("analyze",),
        ("yhw", "wizard"),
        ("tag",),
        ("approve",),
        ("key", "set"),
        ("key", "status"),
        ("key", "delete"),
        ("audio", "setup"),
        ("audio", "voices"),
        ("anki", "check"),
        ("anki", "list"),
        ("anki", "update"),
        ("import",),
        ("backfill-examples",),
        ("backfill-audio",),
        ("retag", "--all"),
        ("reimport", "--all"),
    }


def test_dashboard_shortcuts_are_unique() -> None:
    keys = [action.key for action in ACTIONS]

    assert len(keys) == len(set(keys))
    assert not {"p", "q"}.intersection(keys)


def test_every_dashboard_command_can_start_without_extra_arguments() -> None:
    parser = cli.build_parser()

    for action in ACTIONS:
        parser.parse_args(action.command)


def test_version_management_actions_are_available_without_settings() -> None:
    actions = {action.name: action for action in ACTIONS}

    assert actions["version"].command == ("version",)
    assert actions["upgrade"].command == ("upgrade",)
    assert not actions["version"].needs_settings
    assert not actions["upgrade"].needs_settings


def test_dashboard_actions_are_grouped_by_section() -> None:
    sections = [
        action.section
        for index, action in enumerate(ACTIONS)
        if index == 0 or action.section != ACTIONS[index - 1].section
    ]

    assert sections == [
        "New",
        "Review",
        "Import",
        "Maintenance",
        "Anki",
        "Profiles",
        "Application",
    ]


def test_removed_discovery_commands_are_not_in_dashboard() -> None:
    commands = {part for action in ACTIONS for part in action.command}

    assert "tones" not in commands
    assert "grammar-check" not in commands


def test_dashboard_follows_changed_default_profile(tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")
    app = AnkiiApp(settings_path)
    assert app.profile is not None
    assert app.profile.name == "vietnamese"

    set_default_profile(settings_path, "french")
    app._reload_settings()

    assert app.profile is not None
    assert app.profile.name == "french"


def test_explicit_dashboard_profile_remains_an_override(tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")
    app = AnkiiApp(settings_path, "vietnamese")
    set_default_profile(settings_path, "french")

    app._reload_settings()

    assert app.profile is not None
    assert app.profile.name == "vietnamese"
