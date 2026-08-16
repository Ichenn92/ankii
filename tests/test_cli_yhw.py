import pytest

from ankii import cli


def test_yhw_namespace_parses_source_specific_commands() -> None:
    fetch = cli.build_parser().parse_args(["yhw", "fetch", "123"])
    review = cli.build_parser().parse_args(["yhw", "review", "123"])
    wizard = cli.build_parser().parse_args(["yhw", "wizard", "123"])

    assert (fetch.command, fetch.yhw_command) == ("yhw", "fetch")
    assert (review.command, review.yhw_command) == ("yhw", "review")
    assert (wizard.command, wizard.yhw_command) == ("yhw", "wizard")


def test_old_ambiguous_fetch_command_is_not_exposed() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["fetch", "123"])


def test_help_names_yourhomework_source(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--help"])

    help_text = capsys.readouterr().out
    assert "yhw" in help_text
    assert "yourhomework.net" in help_text
