from pathlib import Path

import pytest

from ankii import cli


def test_no_subcommand_launches_tui(monkeypatch, tmp_path: Path) -> None:
    settings_path = tmp_path / "anki.toml"
    launched = []
    monkeypatch.setattr(
        "ankii.tui.run_tui",
        lambda path, profile: launched.append((path, profile)) or 0,
    )
    monkeypatch.setattr(
        "sys.argv", ["ankii", "--settings", str(settings_path), "--profile", "french"]
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    assert launched == [(settings_path, "french")]
