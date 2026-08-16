from types import SimpleNamespace

from ankii import keychain


def test_environment_key_takes_precedence(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setattr(keychain, "find_keychain_key", lambda: "keychain-key")

    assert keychain.get_openai_api_key() == ("environment-key", "environment")


def test_keychain_key_is_loaded_without_revealing_it(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(keychain.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(keychain.getpass, "getuser", lambda: "tester")
    monkeypatch.setattr(
        keychain.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="stored-key\n"),
    )

    assert keychain.get_openai_api_key() == ("stored-key", "macOS Keychain")


def test_legacy_keychain_service_remains_readable(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(keychain.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(keychain.getpass, "getuser", lambda: "tester")
    results = iter(
        [
            SimpleNamespace(returncode=44, stdout=""),
            SimpleNamespace(returncode=0, stdout="legacy-key\n"),
        ]
    )
    monkeypatch.setattr(keychain.subprocess, "run", lambda *args, **kwargs: next(results))

    assert keychain.get_openai_api_key() == ("legacy-key", "macOS Keychain")
