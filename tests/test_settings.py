from pathlib import Path

import pytest

from ankii.settings import (
    CEFR_LEVELS,
    add_profile,
    create_default_settings,
    data_root,
    load_settings,
    set_default_profile,
)


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_profiles_and_defaults_native_language(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "anki.toml",
        """settings_version = 1
default_profile = "french"
[anki]
vocabulary_model = "Vocabulary"
grammar_model = "Grammar"
[profiles.french]
study_language = "French"
deck = "French"
analysis_min_level = "A1"
analysis_max_level = "C1"
""",
    )

    settings = load_settings(path)
    profile = settings.select_profile()

    assert profile.native_language == "English"
    assert profile.analysis_levels == ("A1", "A2", "B1", "B2", "C1")
    assert profile.review_root == tmp_path / "reviews/french"
    assert profile.language_tag == "language::french"


def test_profile_precedence_is_argument_then_environment(monkeypatch, tmp_path: Path) -> None:
    path = _write(
        tmp_path / "anki.toml",
        """settings_version = 1
default_profile = "vietnamese"
[anki]
vocabulary_model = "Vocabulary"
grammar_model = "Grammar"
[profiles.vietnamese]
study_language = "Vietnamese"
deck = "Vietnamese"
analysis_min_level = "A1"
analysis_max_level = "B2"
[profiles.french]
study_language = "French"
deck = "French"
analysis_min_level = "A1"
analysis_max_level = "B2"
""",
    )
    settings = load_settings(path)
    monkeypatch.setenv("ANKI_PROFILE", "french")

    assert settings.select_profile().name == "french"
    assert settings.select_profile("vietnamese").name == "vietnamese"


@pytest.mark.parametrize(
    ("minimum", "maximum", "message"),
    [("B2", "A1", "ascending"), ("A0", "B2", "one of")],
)
def test_rejects_invalid_level_ranges(
    tmp_path: Path, minimum: str, maximum: str, message: str
) -> None:
    path = _write(
        tmp_path / "anki.toml",
        f"""settings_version = 1
default_profile = "french"
[anki]
vocabulary_model = "Vocabulary"
grammar_model = "Grammar"
[profiles.french]
study_language = "French"
deck = "French"
analysis_min_level = "{minimum}"
analysis_max_level = "{maximum}"
""",
    )

    with pytest.raises(ValueError, match=message):
        load_settings(path)


def test_cefr_scale_includes_advanced_levels() -> None:
    assert CEFR_LEVELS == ("A1", "A2", "B1", "B2", "C1", "C2")


def test_data_root_honors_environment_override(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "private-data"
    monkeypatch.setenv("ANKII_HOME", str(destination))

    assert data_root() == destination


def test_data_root_supports_legacy_environment_override(monkeypatch, tmp_path: Path) -> None:
    destination = tmp_path / "legacy-private-data"
    monkeypatch.delenv("ANKII_HOME", raising=False)
    monkeypatch.setenv("YHW2ANKI_HOME", str(destination))

    assert data_root() == destination


def test_create_default_settings_does_not_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "data" / "anki.toml"
    created_path, created = create_default_settings(path)
    original = created_path.read_text(encoding="utf-8")

    assert created is True
    assert "settings_version = 1" in original
    assert create_default_settings(path) == (path, False)
    assert path.read_text(encoding="utf-8") == original


def test_add_profile_preserves_settings_and_can_make_it_default(tmp_path: Path) -> None:
    path, _created = create_default_settings(tmp_path / "anki.toml")
    original = path.read_text(encoding="utf-8") + "\n# keep this comment\n"
    path.write_text(original, encoding="utf-8")

    profile = add_profile(
        path,
        "spanish",
        "Spanish",
        "English",
        "Spanish",
        "A1",
        "B2",
        make_default=True,
    )

    settings = load_settings(path)
    assert profile.name == "spanish"
    assert settings.default_profile == "spanish"
    assert settings.profiles["spanish"].deck == "Spanish"
    assert profile.review_root.is_dir()
    assert "# keep this comment" in path.read_text(encoding="utf-8")


def test_profile_mutations_reject_duplicate_and_unknown_names(tmp_path: Path) -> None:
    path, _created = create_default_settings(tmp_path / "anki.toml")

    with pytest.raises(ValueError, match="already exists"):
        add_profile(path, "french", "French", "English", "French", "A1", "B2")
    with pytest.raises(ValueError, match="Unknown profile"):
        set_default_profile(path, "missing")
