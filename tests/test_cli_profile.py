from pathlib import Path

import pytest

from ankii import cli
from ankii.settings import create_default_settings, load_settings


def _run_main(monkeypatch, arguments: list[str]) -> int:
    monkeypatch.setattr("sys.argv", ["ankii", *arguments])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    return exit_info.value.code


def test_profile_create_with_arguments_and_set_default(monkeypatch, tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")

    assert (
        _run_main(
            monkeypatch,
            [
                "--settings",
                str(settings_path),
                "profile",
                "create",
                "spanish",
                "--study-language",
                "Spanish",
                "--native-language",
                "English",
                "--deck",
                "Spanish",
                "--min-level",
                "A1",
                "--max-level",
                "B2",
            ],
        )
        == 0
    )
    assert load_settings(settings_path).default_profile == "vietnamese"

    assert (
        _run_main(
            monkeypatch,
            ["--settings", str(settings_path), "profile", "default", "spanish"],
        )
        == 0
    )
    assert load_settings(settings_path).default_profile == "spanish"


def test_profile_create_rejects_invalid_level_order(monkeypatch, tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")

    assert (
        _run_main(
            monkeypatch,
            [
                "--settings",
                str(settings_path),
                "profile",
                "create",
                "spanish",
                "--study-language",
                "Spanish",
                "--native-language",
                "English",
                "--deck",
                "Spanish",
                "--min-level",
                "C1",
                "--max-level",
                "B2",
            ],
        )
        == 1
    )
    assert "spanish" not in load_settings(settings_path).profiles
