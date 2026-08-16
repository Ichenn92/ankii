import argparse

from ankii import cli


def test_removed_discovery_commands_are_not_registered() -> None:
    parser = cli.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert "tones" not in subparsers.choices
    assert "grammar-check" not in subparsers.choices
