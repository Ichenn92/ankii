from pathlib import Path

from ankii.tui import ACTIONS, command_argv


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
