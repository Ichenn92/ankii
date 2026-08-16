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


def test_profile_name_defaults_to_canonical_study_language(monkeypatch, tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")

    assert (
        _run_main(
            monkeypatch,
            [
                "--settings",
                str(settings_path),
                "profile",
                "create",
                "--study-language",
                "gErMaN",
                "--native-language",
                "english",
                "--deck",
                "German",
                "--min-level",
                "A1",
                "--max-level",
                "B2",
            ],
        )
        == 0
    )
    assert load_settings(settings_path).profiles["german"].study_language == "German"


def test_profile_create_rejects_unknown_language(monkeypatch, tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")

    assert (
        _run_main(
            monkeypatch,
            [
                "--settings",
                str(settings_path),
                "profile",
                "create",
                "--study-language",
                "Spanisch",
            ],
        )
        == 2
    )


def test_profile_list_marks_default(monkeypatch, tmp_path: Path, capsys) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")

    assert _run_main(
        monkeypatch, ["--settings", str(settings_path), "profile", "list"]
    ) == 0

    output = capsys.readouterr().out
    assert "vietnamese (default): Vietnamese -> English [Vietnamese]" in output


def test_profile_delete_preserves_reviews(monkeypatch, tmp_path: Path, capsys) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")
    assert _run_main(
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
    ) == 0
    review_root = load_settings(settings_path).profiles["spanish"].review_root
    review_file = review_root / "saved.review.json"
    review_file.write_text("{}", encoding="utf-8")

    assert _run_main(
        monkeypatch,
        ["--settings", str(settings_path), "profile", "delete", "spanish", "--yes"],
    ) == 0

    assert "spanish" not in load_settings(settings_path).profiles
    assert review_file.exists()
    assert f"Review files preserved at: {review_root}" in capsys.readouterr().out


def test_profile_delete_can_replace_default(monkeypatch, tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")
    assert _run_main(
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
    ) == 0

    assert _run_main(
        monkeypatch,
        [
            "--settings",
            str(settings_path),
            "profile",
            "delete",
            "vietnamese",
            "--new-default",
            "spanish",
            "--yes",
        ],
    ) == 0

    settings = load_settings(settings_path)
    assert "vietnamese" not in settings.profiles
    assert settings.default_profile == "spanish"


def test_profile_delete_confirmation_can_cancel(monkeypatch, tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")
    assert _run_main(
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
    ) == 0
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")

    assert _run_main(
        monkeypatch,
        ["--settings", str(settings_path), "profile", "delete", "spanish"],
    ) == 0

    assert "spanish" in load_settings(settings_path).profiles


def test_profile_delete_accepts_delete_confirmation(monkeypatch, tmp_path: Path) -> None:
    settings_path, _created = create_default_settings(tmp_path / "anki.toml")
    assert _run_main(
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
    ) == 0
    monkeypatch.setattr("builtins.input", lambda _prompt: "DELETE")

    assert _run_main(
        monkeypatch,
        ["--settings", str(settings_path), "profile", "delete", "spanish"],
    ) == 0

    assert "spanish" not in load_settings(settings_path).profiles
