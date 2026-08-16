import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from ankii import cli
from ankii.audio import AudioFailure, AudioGenerationResult
from ankii.cli import run_import
from ankii.importer import FIELD_DEFAULTS
from ankii.review import save_review
from ankii.settings import AudioSettings, LanguageProfile
from ankii.tone_family import (
    TONE_NAMES,
    ToneEntry,
    ToneFamily,
    ToneSense,
    tone_family_to_review,
    tone_variants,
)


def test_import_archives_only_successful_ready_cards(tmp_path: Path) -> None:
    cards = [
        {"word": "one", "approved": True, "skip": False},
        {"word": "duplicate", "approved": True, "skip": False},
        {"word": "failed", "approved": True, "skip": False},
    ]
    review = {
        "review_version": 1,
        "review_kind": "manual_inbox",
        "lesson": {},
        "cards": cards,
    }
    args = argparse.Namespace(
        review_file=tmp_path / "inbox.review.json",
        deck="Vietnamese",
        model="Vietnamese Vocabulary",
        **{f"field_{key}": value for key, value in FIELD_DEFAULTS.items()},
    )

    with (
        patch(
            "ankii.cli.prepare_import",
            return_value=(review, [{}, {}, {}], [True, False, True]),
        ),
        patch("ankii.cli.add_notes", return_value=[101, None]),
        patch("ankii.cli.archive_imported_cards") as archive,
        patch("builtins.input", return_value="IMPORT"),
    ):
        result = run_import(args)

    assert result == 1
    archive.assert_called_once_with(
        args.review_file,
        review,
        [(0, 101)],
        "Vietnamese",
        "Vietnamese Vocabulary",
    )


def test_regular_review_moves_to_archive_when_complete(tmp_path: Path) -> None:
    from ankii.inbox import archive_completed_review

    path = tmp_path / "123.review.json"
    path.write_text('{"review_version": 1, "lesson": {}, "cards": []}', encoding="utf-8")

    assert archive_completed_review(path) == tmp_path / "archive/123.review.json"
    assert not path.exists()
    assert (tmp_path / "archive/123.review.json").exists()


def test_successful_regular_import_archives_whole_review(tmp_path: Path) -> None:
    review = {
        "review_version": 1,
        "lesson": {},
        "cards": [{"word": "one", "approved": True, "skip": False}],
    }
    args = argparse.Namespace(
        review_file=tmp_path / "123.review.json",
        deck="Vietnamese",
        model="Vietnamese Vocabulary",
        **{f"field_{key}": value for key, value in FIELD_DEFAULTS.items()},
    )

    with (
        patch("ankii.cli.prepare_import", return_value=(review, [{}], [True])),
        patch("ankii.cli.add_notes", return_value=[101]),
        patch("ankii.cli.archive_imported_cards", return_value=None),
        patch("ankii.cli.archive_completed_review") as archive,
        patch("builtins.input", return_value="IMPORT"),
    ):
        result = run_import(args)

    assert result == 0
    archive.assert_called_once_with(args.review_file)


def test_import_summary_lists_actual_mixed_note_types(tmp_path: Path, capsys) -> None:
    review = {
        "review_version": 1,
        "lesson": {},
        "cards": [
            {"word": "one", "approved": True, "skip": False},
            {"word": "pattern", "approved": True, "skip": False},
        ],
    }
    args = argparse.Namespace(
        review_file=tmp_path / "mixed.review.json",
        deck="Vietnamese",
        model="Vocabulary",
        grammar_model="Grammar",
        **{f"field_{key}": value for key, value in FIELD_DEFAULTS.items()},
    )
    notes = [{"modelName": "Vocabulary"}, {"modelName": "Grammar"}]

    with (
        patch("ankii.cli.prepare_import", return_value=(review, notes, [True, True])),
        patch("builtins.input", return_value="cancel"),
    ):
        assert run_import(args) == 0

    output = capsys.readouterr().out
    assert "Note types detected:\n  Vocabulary: 1\n  Grammar: 1" in output


def test_import_generates_audio_after_confirmation_for_ready_vocabulary_only(
    tmp_path: Path,
) -> None:
    cards = [
        {"word": "one", "approved": True, "skip": False},
        {"word": "grammar", "approved": True, "skip": False},
        {"word": "duplicate", "approved": True, "skip": False},
    ]
    review = {"review_version": 2, "lesson": {}, "cards": cards}
    vocabulary = {
        "modelName": "Vocabulary",
        "fields": {"Target Audio": "", "Example Audio": ""},
    }
    grammar = {"modelName": "Grammar", "fields": {}}
    duplicate = {
        "modelName": "Vocabulary",
        "fields": {"Target Audio": "", "Example Audio": ""},
    }
    args = argparse.Namespace(
        review_file=tmp_path / "review.json",
        deck="Vietnamese",
        model="Vocabulary",
        grammar_model="Grammar",
        **{f"field_{key}": value for key, value in FIELD_DEFAULTS.items()},
    )
    profile = LanguageProfile(
        "vietnamese",
        "Vietnamese",
        "English",
        "Vietnamese",
        "A1",
        "B2",
        review_base=tmp_path / "reviews",
        audio=AudioSettings(enabled=True),
    )
    client = object()

    with (
        patch(
            "ankii.cli.prepare_import",
            return_value=(review, [vocabulary, grammar, duplicate], [True, True, False]),
        ),
        patch("ankii.cli.create_speech_client", return_value=client),
        patch(
            "ankii.cli.attach_audio",
            return_value=AudioGenerationResult(1, 0, (AudioFailure("bad", "failed"),)),
        ) as generate,
        patch("ankii.cli.add_notes", return_value=[101, 102]) as add,
        patch("ankii.cli.archive_imported_cards", return_value=None),
        patch("ankii.cli.archive_completed_review", return_value=None),
        patch("builtins.input", return_value="IMPORT"),
    ):
        assert run_import(args, profile) == 0

    assert generate.call_args.args[:2] == ([(vocabulary, cards[0])], profile)
    add.assert_called_once_with([vocabulary, grammar])


def test_audio_enabled_import_requires_audio_fields(tmp_path: Path) -> None:
    review = {
        "review_version": 2,
        "lesson": {},
        "cards": [{"word": "one", "approved": True, "skip": False}],
    }
    note = {"modelName": "Vocabulary", "fields": {"Target": "one"}}
    args = argparse.Namespace(
        review_file=tmp_path / "review.json",
        deck="Vietnamese",
        model="Vocabulary",
        grammar_model="Grammar",
        **{f"field_{key}": value for key, value in FIELD_DEFAULTS.items()},
    )
    profile = LanguageProfile(
        "vietnamese",
        "Vietnamese",
        "English",
        "Vietnamese",
        "A1",
        "B2",
        audio=AudioSettings(enabled=True),
    )

    with (
        patch("ankii.cli.prepare_import", return_value=(review, [note], [True])),
        patch("ankii.cli.create_speech_client") as client,
        pytest.raises(ValueError, match="missing audio fields"),
    ):
        run_import(args, profile)

    client.assert_not_called()


def test_cancelled_import_does_not_generate_audio(tmp_path: Path) -> None:
    review = {
        "review_version": 2,
        "lesson": {},
        "cards": [{"word": "one", "approved": True, "skip": False}],
    }
    note = {
        "modelName": "Vocabulary",
        "fields": {"Target Audio": "", "Example Audio": ""},
    }
    args = argparse.Namespace(
        review_file=tmp_path / "review.json",
        deck="Vietnamese",
        model="Vocabulary",
        grammar_model="Grammar",
        **{f"field_{key}": value for key, value in FIELD_DEFAULTS.items()},
    )
    profile = LanguageProfile(
        "vietnamese",
        "Vietnamese",
        "English",
        "Vietnamese",
        "A1",
        "B2",
        audio=AudioSettings(enabled=True),
    )

    with (
        patch("ankii.cli.prepare_import", return_value=(review, [note], [True])),
        patch("ankii.cli.create_speech_client", return_value=object()),
        patch("ankii.cli.attach_audio") as generate,
        patch("builtins.input", return_value="cancel"),
    ):
        assert run_import(args, profile) == 0

    generate.assert_not_called()


def test_import_arguments_are_optional() -> None:
    args = cli.build_parser().parse_args(["import"])

    assert args.review_file is None
    assert args.deck is None
    assert args.model == "Vocabulary"
    assert args.grammar_model == "Grammar"


def test_import_dispatches_saved_tone_family_review(tmp_path: Path) -> None:
    forms = tone_variants("ma")
    family = ToneFamily(
        "ma",
        [
            ToneEntry(
                tone,
                forms[tone],
                [ToneSense("ghost", "noun", "Con ma.", "A ghost.")] if tone == "level" else [],
                "rare" if tone != "level" else "",
                tone == "level",
                [
                    "part_of_speech::noun",
                    "topic::other",
                    "register::neutral",
                    "level::A1",
                ]
                if tone == "level"
                else [],
            )
            for tone in TONE_NAMES
        ],
        "",
        "test-model",
    )
    path = tmp_path / "ma.review.json"
    save_review(tone_family_to_review(family), path)
    args = argparse.Namespace(
        review_file=path,
        deck="Vietnamese",
        model="Vocabulary",
        grammar_model="Grammar",
        tone_model=None,
        **{f"field_{key}": None for key in FIELD_DEFAULTS},
    )
    with patch("ankii.cli.run_tone_import", return_value=0) as tone_import:
        assert run_import(args) == 0
    tone_import.assert_called_once_with(family, "Vietnamese", "ToneFamily", "Vocabulary", path)


def test_import_prompts_for_file_and_deck_but_detects_models(monkeypatch, tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    inbox = reviews / "inbox.review.json"
    inbox.write_text("{}", encoding="utf-8")
    archive = reviews / "archive"
    archive.mkdir()
    (archive / "old.review.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    answers = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    invoke_results = iter([["Default", "Vietnamese"]])
    monkeypatch.setattr(cli, "invoke", lambda *args, **kwargs: next(invoke_results))
    args = argparse.Namespace(review_file=None, deck=None, model=None)

    cli._resolve_import_destination(args)

    assert args.review_file == Path("reviews/inbox.review.json")
    assert args.deck == "Vietnamese"
    assert args.model == "Vocabulary"
