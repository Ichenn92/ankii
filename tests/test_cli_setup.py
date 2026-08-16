from pathlib import Path

from ankii import cli


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
