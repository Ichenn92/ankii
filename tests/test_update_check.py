from __future__ import annotations

from types import SimpleNamespace

import pytest

from ankii import __version__, update_check


def test_version_comparison() -> None:
    assert update_check._newer_version("0.2.0", "0.1.9")
    assert not update_check._newer_version("0.1.0", "0.1.0")
    assert not update_check._newer_version("0.0.9", "0.1.0")
    assert not update_check._newer_version("not-a-version", "0.1.0")


def test_check_version_reports_available_update(monkeypatch, capsys) -> None:
    monkeypatch.setattr(update_check, "_fetch_latest_version", lambda: "9.9.9")

    assert update_check.check_version() == 0
    output = capsys.readouterr().out
    assert f"Installed: {__version__}" in output
    assert "Latest:    9.9.9" in output
    assert "ankii upgrade" in output


def test_upgrade_runs_pipx(monkeypatch, capsys) -> None:
    monkeypatch.setattr(update_check.shutil, "which", lambda command: "/usr/local/bin/pipx")
    calls = []
    monkeypatch.setattr(
        update_check.subprocess,
        "run",
        lambda command, check: calls.append((command, check)) or SimpleNamespace(returncode=0),
    )

    assert update_check.upgrade() == 0
    assert calls == [(["pipx", "upgrade", "ankii"], False)]
    assert "Restart ankii" in capsys.readouterr().out


def test_upgrade_requires_pipx(monkeypatch) -> None:
    monkeypatch.setattr(update_check.shutil, "which", lambda command: None)

    with pytest.raises(RuntimeError, match="pipx is not available"):
        update_check.upgrade()
