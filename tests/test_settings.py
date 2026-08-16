from pathlib import Path

import pytest

from ankii.settings import (
    AVAILABLE_LANGUAGES,
    CEFR_LEVELS,
    AudioSettings,
    add_profile,
    canonical_language,
    create_default_settings,
    data_root,
    delete_profile,
    load_settings,
    profile_name_for_language,
    set_default_profile,
)


def _add_spanish_profile(path: Path) -> None:
    add_profile(path, "spanish", "Spanish", "English", "Spanish", "A1", "B2")


def test_delete_profile_preserves_review_files(tmp_path: Path) -> None:
    path, _created = create_default_settings(tmp_path / "anki.toml")
    _add_spanish_profile(path)
    review_root = load_settings(path).profiles["spanish"].review_root
    review_file = review_root / "archive" / "saved.review.json"
    review_file.parent.mkdir(parents=True)
    review_file.write_text("{}", encoding="utf-8")

    settings, deleted_review_root = delete_profile(path, "spanish")

    assert "spanish" not in settings.profiles
    assert deleted_review_root == review_root
    assert review_file.exists()


def test_delete_profile_removes_nested_audio_table(tmp_path: Path) -> None:
    path, _created = create_default_settings(tmp_path / "anki.toml")
    text = path.read_text(encoding="utf-8").replace(
        "\n[profiles.french]",
        "\n[profiles.vietnamese.audio]\nenabled = true\n\n[profiles.french]",
    )
    path.write_text(text, encoding="utf-8")

    settings, _review_root = delete_profile(path, "vietnamese", new_default="french")

    assert "vietnamese" not in settings.profiles
    assert "profiles.vietnamese.audio" not in path.read_text(encoding="utf-8")


def test_delete_default_profile_requires_and_applies_replacement(tmp_path: Path) -> None:
    path, _created = create_default_settings(tmp_path / "anki.toml")
    _add_spanish_profile(path)

    with pytest.raises(ValueError, match="requires a new default"):
        delete_profile(path, "vietnamese")

    settings, _review_root = delete_profile(path, "vietnamese", new_default="spanish")

    assert settings.default_profile == "spanish"
    assert "vietnamese" not in settings.profiles
    assert "spanish" in settings.profiles


def test_delete_only_profile_is_rejected(tmp_path: Path) -> None:
    path, _created = create_default_settings(tmp_path / "anki.toml")
    delete_profile(path, "french")

    with pytest.raises(ValueError, match="only profile"):
        delete_profile(path, "vietnamese", new_default="vietnamese")


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
    assert profile.audio is None


def test_loads_profile_audio_settings(tmp_path: Path) -> None:
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
[profiles.vietnamese.audio]
enabled = true
provider = "openai"
model = "gpt-4o-mini-tts"
voice = "marin"
accent = "Southern Vietnamese (Saigon)"
instructions = "Speak clearly."
""",
    )

    profile = load_settings(path).select_profile()

    assert profile.audio == AudioSettings(
        enabled=True,
        provider="openai",
        model="gpt-4o-mini-tts",
        voice="marin",
        accent="Southern Vietnamese (Saigon)",
        instructions="Speak clearly.",
    )
    assert profile.audio_cache_path == tmp_path / "reviews/vietnamese/audio"
    assert profile.audio_skip_path == tmp_path / "reviews/vietnamese/audio-skip.json"


@pytest.mark.parametrize(
    ("audio_line", "message"),
    [
        ('enabled = "yes"', "enabled must be true or false"),
        ('provider = "local"', "provider must be 'openai'"),
        ('voice = ""', "voice must be a non-empty string"),
        ("accent = 42", "accent must be a string"),
    ],
)
def test_rejects_invalid_audio_settings(
    tmp_path: Path, audio_line: str, message: str
) -> None:
    path = _write(
        tmp_path / "anki.toml",
        f"""settings_version = 1
default_profile = "vietnamese"
[anki]
vocabulary_model = "Vocabulary"
grammar_model = "Grammar"
[profiles.vietnamese]
study_language = "Vietnamese"
deck = "Vietnamese"
analysis_min_level = "A1"
analysis_max_level = "B2"
[profiles.vietnamese.audio]
{audio_line}
""",
    )

    with pytest.raises(ValueError, match=message):
        load_settings(path)


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


def test_languages_are_canonical_and_generate_default_profile_names() -> None:
    assert "Spanish" in AVAILABLE_LANGUAGES
    assert canonical_language("sPaNiSh") == "Spanish"
    assert profile_name_for_language("Spanish") == "spanish"
    assert profile_name_for_language("Mandarin Chinese") == "mandarin-chinese"

    with pytest.raises(ValueError, match="profile languages"):
        canonical_language("Spanisch")


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
