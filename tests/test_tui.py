from pathlib import Path

from ankii.settings import create_default_settings, set_default_profile
from ankii.tui import ACTIONS, AnkiiApp, command_argv


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
