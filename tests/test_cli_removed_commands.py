import argparse

from ankii import cli


def test_removed_discovery_commands_are_not_registered() -> None:
    parser = cli.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )

    assert "tones" not in subparsers.choices
    assert "grammar-check" not in subparsers.choices

    anki_parser = subparsers.choices["anki"]
    anki_subparsers = next(
        action
        for action in anki_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert "migrate-tone-families" not in anki_subparsers.choices

    audio_parser = subparsers.choices["audio"]
    audio_subparsers = next(
        action
        for action in audio_parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    assert "cleanup" not in audio_subparsers.choices
