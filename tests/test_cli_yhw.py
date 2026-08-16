import pytest

from ankii import cli


def test_yhw_namespace_exposes_only_wizard() -> None:
    wizard = cli.build_parser().parse_args(["yhw", "wizard", "123"])

    assert (wizard.command, wizard.yhw_command) == ("yhw", "wizard")

    for removed_command in ("fetch", "review"):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(["yhw", removed_command, "123"])


def test_old_ambiguous_fetch_command_is_not_exposed() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["fetch", "123"])


def test_help_names_yourhomework_source(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--help"])

    help_text = capsys.readouterr().out
    assert "yhw" in help_text
    assert "yourhomework.net" in help_text
