from dataclasses import replace
from pathlib import Path

from ankii import cli
from ankii.grammar_check import GrammarSuggestion, load_ignored


def _suggestion() -> GrammarSuggestion:
    return GrammarSuggestion(
        pattern="có … thì …",
        explanation="Creates a conditional meaning.",
        example_vn="Anh có thương thì qua.",
        example_en="If you care, come over.",
        everyday_example_vn="Có việc gì thì gọi cho tôi nhé.",
        everyday_example_en="If anything comes up, call me.",
        tags=[
            "part_of_speech::other",
            "topic::communication",
            "register::neutral",
            "level::B1",
        ],
        source_note_id=12,
        source_word="thương",
        source="A song",
    )


def test_parse_grammar_actions_supports_create_reject_and_defer() -> None:
    assert cli._parse_grammar_actions("1,3-4,x2,x6-7", 8) == (
        [0, 2, 3],
        [1, 5, 6],
    )


def test_grammar_check_applies_create_and_rejection(monkeypatch, tmp_path: Path) -> None:
    ignore_path = tmp_path / "ignore.json"
    suggestions = [_suggestion(), replace(_suggestion(), pattern="đừng + V")]
    actions = []

    def fake_invoke(action, **params):
        actions.append((action, params))
        return {
            "modelNames": ["Vocabulary", "Grammar"],
            "deckNames": ["Vietnamese"],
            "canAddNotes": [True],
        }[action]

    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(
        cli,
        "discover_grammar",
        lambda *_args: (
            suggestions,
            {"notes": 2, "analyzed": 2, "skipped": 0, "suggestions": 2},
        ),
    )
    monkeypatch.setattr(cli, "build_grammar_note", lambda card, *_args: card)
    monkeypatch.setattr(cli, "add_notes", lambda notes: [123] * len(notes))
    answers = iter(["1,x2", "APPLY"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    result = cli.run_grammar_check("Vocabulary", "Grammar", "Vietnamese", "m", ignore_path)

    assert result == 0
    assert any(action == "canAddNotes" for action, _params in actions)
    assert normalize_keys(load_ignored(ignore_path)) == {"đừng + v"}


def normalize_keys(value):
    return set(value)


def test_grammar_check_cancel_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    ignore_path = tmp_path / "ignore.json"
    monkeypatch.setattr(
        cli,
        "invoke",
        lambda action, **_params: {
            "modelNames": ["Vocabulary", "Grammar"],
            "deckNames": ["Vietnamese"],
        }[action],
    )
    monkeypatch.setattr(
        cli,
        "discover_grammar",
        lambda *_args: (
            [_suggestion()],
            {"notes": 1, "analyzed": 1, "skipped": 0, "suggestions": 1},
        ),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "c")

    assert cli.run_grammar_check("Vocabulary", "Grammar", "Vietnamese", "m", ignore_path) == 0
    assert not ignore_path.exists()


def test_grammar_check_confirmation_cancel_writes_nothing(monkeypatch, tmp_path: Path) -> None:
    ignore_path = tmp_path / "ignore.json"

    def fake_invoke(action, **_params):
        return {
            "modelNames": ["Vocabulary", "Grammar"],
            "deckNames": ["Vietnamese"],
            "canAddNotes": [True],
        }[action]

    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(
        cli,
        "discover_grammar",
        lambda *_args: (
            [_suggestion()],
            {"notes": 1, "analyzed": 1, "skipped": 0, "suggestions": 1},
        ),
    )
    monkeypatch.setattr(cli, "build_grammar_note", lambda card, *_args: card)
    monkeypatch.setattr(
        cli, "add_notes", lambda _notes: (_ for _ in ()).throw(AssertionError("write"))
    )
    answers = iter(["x1", "no"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli.run_grammar_check("Vocabulary", "Grammar", "Vietnamese", "m", ignore_path) == 0
    assert not ignore_path.exists()
