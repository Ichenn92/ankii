from pathlib import Path
from unittest.mock import call, patch

from ankii import cli
from ankii.audio import LocalVoice
from ankii.settings import LanguageProfile, load_settings


def test_setup_creates_settings_and_profile_directories(monkeypatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "local-data" / "anki.toml"
    monkeypatch.setattr(cli, "get_openai_api_key", lambda: (None, None))

    assert cli.run_setup(settings_path, skip_key=True) == 0
    assert settings_path.exists()
    assert (settings_path.parent / "reviews" / "vietnamese").is_dir()
    assert (settings_path.parent / "reviews" / "french").is_dir()


def test_setup_stores_key_in_macos_keychain(monkeypatch, tmp_path: Path) -> None:
    stored = []
    monkeypatch.setattr(cli, "get_openai_api_key", lambda: (None, None))
    monkeypatch.setattr(cli, "keychain_supported", lambda: True)
    monkeypatch.setattr(cli, "store_keychain_key", lambda: stored.append(True))
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    assert cli.run_setup(tmp_path / "anki.toml") == 0
    assert stored == [True]


def test_key_command_does_not_require_settings(monkeypatch) -> None:
    monkeypatch.setattr(cli, "run_key", lambda command: 0 if command == "status" else 1)
    monkeypatch.setattr(cli, "load_settings", lambda _path: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr("sys.argv", ["ankii", "key", "status"])

    try:
        cli.main()
    except SystemExit as exc:
        assert exc.code == 0


def test_audio_setup_writes_active_profile_configuration(monkeypatch, tmp_path) -> None:
    settings_path, _created = cli.create_default_settings(tmp_path / "anki.toml")
    answers = iter(["", "", "", "", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli.run_audio_setup(settings_path, "vietnamese") == 0

    audio = load_settings(settings_path).profiles["vietnamese"].audio
    assert audio is not None
    assert audio.enabled
    assert audio.model == "gpt-4o-mini-tts"
    assert audio.voice == "marin"
    assert audio.accent == "Southern Vietnamese (Saigon)"
    assert audio.instructions == "Speak clearly at a natural, learner-friendly pace."


def test_audio_setup_can_be_supplied_without_prompts(monkeypatch, tmp_path) -> None:
    settings_path, _created = cli.create_default_settings(tmp_path / "anki.toml")
    monkeypatch.setattr(
        "builtins.input", lambda _prompt: (_ for _ in ()).throw(AssertionError("prompted"))
    )

    assert cli.run_audio_setup(
        settings_path,
        "french",
        enabled=True,
        provider="openai",
        model="gpt-4o-mini-tts",
        voice="cedar",
        accent="Parisian French",
        instructions="Speak slowly.",
    ) == 0

    audio = load_settings(settings_path).profiles["french"].audio
    assert audio is not None
    assert audio.voice == "cedar"
    assert audio.accent == "Parisian French"


def test_audio_setup_selects_an_installed_local_language_voice(monkeypatch, tmp_path) -> None:
    settings_path, _created = cli.create_default_settings(tmp_path / "anki.toml")
    monkeypatch.setattr(cli, "local_voices", lambda _language: [LocalVoice("Linh", "vi_VN")])

    assert cli.run_audio_setup(
        settings_path,
        "vietnamese",
        enabled=True,
        provider="local",
        voice="Linh",
        language="vi_VN",
    ) == 0

    audio = load_settings(settings_path).profiles["vietnamese"].audio
    assert audio is not None
    assert audio.provider == "local"
    assert audio.model == "macos-say"
    assert audio.voice == "Linh"
    assert audio.language == "vi_VN"


@patch("ankii.cli.invoke")
def test_disables_deck_audio_autoplay_but_keeps_other_options(invoke) -> None:
    config = {"id": 42, "name": "Vietnamese", "autoplay": True, "replayq": True}
    invoke.side_effect = [config, True]

    assert cli._disable_deck_audio_autoplay("Vietnamese")

    assert config["autoplay"] is True
    assert call(
        "saveDeckConfig",
        config={"id": 42, "name": "Vietnamese", "autoplay": False, "replayq": True},
    ) in invoke.mock_calls


@patch("ankii.cli.invoke")
def test_bootstrap_note_types_creates_profile_deck(invoke, monkeypatch) -> None:
    profile = LanguageProfile("french", "French", "English", "French", "A1", "B2")
    calls = []
    monkeypatch.setattr(
        cli,
        "bootstrap_learning_models",
        lambda vocabulary, grammar: calls.append((vocabulary, grammar))
        or {"vocabulary_created": 1, "grammar_created": 1},
    )
    monkeypatch.setattr(cli, "_disable_deck_audio_autoplay", lambda _deck: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "CREATE")
    invoke.return_value = []

    assert cli.run_anki(
        "bootstrap-note-types",
        profile=profile,
        vocabulary_model="Words",
        grammar_model="Rules",
    ) == 0

    assert calls == [("Words", "Rules")]
    assert call("createDeck", deck="French") in invoke.mock_calls
