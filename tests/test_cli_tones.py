import pytest

from ankii import cli
from ankii.tone_family import (
    TONE_NAMES,
    ToneEntry,
    ToneFamily,
    ToneSense,
    build_tone_family_note,
    tone_variants,
)


def _family() -> ToneFamily:
    forms = tone_variants("ma")
    return ToneFamily(
        base="ma",
        model="test-model",
        explanation="",
        entries=[
            ToneEntry(
                tone=tone,
                form=forms[tone],
                senses=[
                    ToneSense(
                        tone,
                        "noun",
                        f"Đây là {forms[tone]}.",
                        f"This is {tone}.",
                    )
                ],
                usage_note="",
                common=True,
                tags=[
                    "part_of_speech::noun",
                    "topic::other",
                    "register::neutral",
                    "level::A1",
                ],
            )
            for tone in TONE_NAMES
        ],
    )


def _single_entry_family() -> ToneFamily:
    family = _family()
    for entry in family.entries[1:]:
        entry.common = False
        entry.senses = []
        entry.tags = []
        entry.usage_note = "not common"
    return family


def test_tones_cancel_does_not_contact_anki(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "generate_tone_family", lambda *_args: _family())
    monkeypatch.setattr("builtins.input", lambda _prompt: "c")

    def fail_invoke(*_args, **_kwargs):
        raise AssertionError("Anki should not be contacted")

    monkeypatch.setattr(cli, "invoke", fail_invoke)
    assert cli.run_tones("má", tmp_path / "ma.json", "ToneFamily", "Vocabulary", "test-model") == 0


def test_tones_saves_review_json_without_contacting_anki(monkeypatch, tmp_path) -> None:
    output = tmp_path / "ma.review.json"
    monkeypatch.setattr(cli, "generate_tone_family", lambda *_args: _family())
    monkeypatch.setattr("builtins.input", lambda _prompt: "s")

    def fail_invoke(*_args, **_kwargs):
        raise AssertionError("Anki should not be contacted")

    monkeypatch.setattr(cli, "invoke", fail_invoke)
    assert cli.run_tones("ma", output, "ToneFamily", "Vocabulary", "test-model") == 0
    review = cli.load_review(output)
    assert review["review_kind"] == "tone_family"
    assert review["tone_family"]["base"] == "ma"
    assert "tone_model" not in review["tone_family"]
    assert len(review["cards"]) == 6


def test_tones_adds_note_after_confirmation(monkeypatch) -> None:
    actions = []

    def fake_invoke(action, **kwargs):
        actions.append((action, kwargs))
        return {
            "deckNames": ["Vietnamese"],
            "modelNames": ["Vocabulary"],
            "modelFieldNames": ["Vietnamese", "English", "Example VN", "Example EN"],
            "findNotes": [],
            "canAddNotes": [True] * 6,
            "addNotes": [201, 202, 203, 204, 205, 206],
        }[action]

    answers = iter(["IMPORT"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "generate_tone_family", lambda *_args: _family())
    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(cli, "setup_vocabulary_related_words", lambda _model: None)

    assert cli.run_tone_import(_family(), "Vietnamese", "ToneFamily", "Vocabulary") == 0
    assert [action for action, _kwargs in actions].count("findNotes") == 6
    assert [action for action, _kwargs in actions][-1:] == ["addNotes"]
    assert not any(action == "addNote" for action, _kwargs in actions)


def test_tones_rejects_family_without_common_vocabulary_forms(monkeypatch) -> None:
    family = _single_entry_family()
    family.entries[0].common = False
    monkeypatch.setattr(
        cli,
        "invoke",
        lambda action, **_kwargs: {
            "deckNames": ["Vietnamese"],
            "modelNames": ["Vocabulary"],
            "modelFieldNames": ["Vietnamese", "English"],
        }.get(action, []),
    )
    with pytest.raises(ValueError, match="no common forms"):
        cli.run_tone_import(family, "Vietnamese", "ToneFamily", "Vocabulary")


def test_tones_links_unique_existing_vocabulary_without_overwriting(monkeypatch) -> None:
    actions = []

    def fake_invoke(action, **kwargs):
        actions.append((action, kwargs))
        if action == "deckNames":
            return ["Vietnamese"]
        if action == "modelNames":
            return ["Vocabulary"]
        if action == "modelFieldNames":
            return ["Vietnamese", "English", "Related Words"]
        if action == "findNotes":
            return [10]
        if action == "notesInfo":
            return [
                {
                    "noteId": 10,
                    "fields": {
                        "Vietnamese": {"value": "ma"},
                        "English": {"value": "existing meaning"},
                        "Related Words": {"value": ""},
                    },
                    "tags": ["keep-me"],
                }
            ]
        if action in {"updateNoteFields", "addTags"}:
            return None
        raise AssertionError(action)

    answers = iter(["IMPORT"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "generate_tone_family", lambda *_args: _single_entry_family())
    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(cli, "setup_vocabulary_related_words", lambda _model: None)

    assert (
        cli.run_tone_import(_single_entry_family(), "Vietnamese", "ToneFamily", "Vocabulary") == 0
    )
    assert not any(action == "addNotes" for action, _kwargs in actions)
    update = next(kwargs for action, kwargs in actions if action == "updateNoteFields")
    assert set(update["note"]["fields"]) == {"Related Words"}
    assert "related-words-table" in update["note"]["fields"]["Related Words"]


def test_tones_reports_vocabulary_add_failure_without_recap_note(monkeypatch) -> None:
    deleted = []

    def fake_invoke(action, **kwargs):
        if action == "deckNames":
            return ["Vietnamese"]
        if action == "modelNames":
            return ["Vocabulary"]
        if action == "modelFieldNames":
            return ["Vietnamese", "English"]
        if action == "findNotes":
            return []
        if action == "canAddNotes":
            return [True]
        if action == "addNotes":
            return [None]
        if action == "deleteNotes":
            deleted.extend(kwargs["notes"])
            return None
        raise AssertionError(action)

    answers = iter(["IMPORT"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "generate_tone_family", lambda *_args: _single_entry_family())
    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(cli, "setup_vocabulary_related_words", lambda _model: None)

    try:
        cli.run_tone_import(_single_entry_family(), "Vietnamese", "ToneFamily", "Vocabulary")
    except RuntimeError as exc:
        assert "failed to add" in str(exc)
    else:
        raise AssertionError("failed child insertion was not reported")
    assert deleted == []


def test_migrate_tone_families_embeds_then_deletes_legacy_notes(monkeypatch) -> None:
    actions = []
    family = _single_entry_family()
    parent = build_tone_family_note(family, "Vietnamese", "ToneFamily")
    parent = {
        "noteId": 90,
        "fields": {name: {"value": value} for name, value in parent["fields"].items()},
        "tags": parent["tags"],
    }
    vocabulary = {
        "noteId": 10,
        "fields": {
            "Vietnamese": {"value": "ma"},
            "English": {"value": "existing"},
            "Tone Family": {"value": "old link"},
        },
        "tags": ["keep-me", "tone_family::ma"],
    }

    def fake_invoke(action, **kwargs):
        actions.append((action, kwargs))
        if action == "modelNames":
            return ["ToneFamily", "Vocabulary"]
        if action == "modelFieldNames":
            return ["Vietnamese", "English", "Tone Family", "Related Words"]
        if action == "findNotes":
            return [90] if kwargs["query"] == 'note:"ToneFamily"' else [10]
        if action == "notesInfo":
            return [parent] if kwargs["notes"] == [90] else [vocabulary]
        if action in {"updateNoteFields", "deleteNotes", "modelFieldRemove"}:
            return None
        raise AssertionError(action)

    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(cli, "setup_vocabulary_related_words", lambda _model: None)
    monkeypatch.setattr("builtins.input", lambda _prompt: "MIGRATE")

    assert cli.run_tone_migration("Vocabulary") == 0
    update = next(kwargs for action, kwargs in actions if action == "updateNoteFields")
    assert "related-words-table" in update["note"]["fields"]["Related Words"]
    assert next(kwargs for action, kwargs in actions if action == "deleteNotes")["notes"] == [90]
    remove = next(kwargs for action, kwargs in actions if action == "modelFieldRemove")
    assert remove["fieldName"] == "Tone Family"


def test_migrate_tone_families_preflight_failure_makes_no_changes(monkeypatch) -> None:
    family = _single_entry_family()
    parent = build_tone_family_note(family, "Vietnamese", "ToneFamily")
    parent["noteId"] = 90
    parent["fields"] = {name: {"value": value} for name, value in parent["fields"].items()}
    actions = []

    def fake_invoke(action, **kwargs):
        actions.append(action)
        if action == "modelNames":
            return ["ToneFamily", "Vocabulary"]
        if action == "modelFieldNames":
            return ["Vietnamese", "English", "Tone Family"]
        if action == "findNotes":
            return [90] if kwargs["query"] == 'note:"ToneFamily"' else []
        if action == "notesInfo":
            return [parent]
        raise AssertionError(action)

    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(
        cli,
        "setup_vocabulary_related_words",
        lambda _model: (_ for _ in ()).throw(AssertionError("must not mutate")),
    )

    assert cli.run_tone_migration("Vocabulary") == 1
    assert "updateNoteFields" not in actions
    assert "deleteNotes" not in actions


def test_migrate_tone_families_command_defaults_to_legacy_model() -> None:
    args = cli.build_parser().parse_args(["anki", "migrate-tone-families"])

    assert args.anki_command == "migrate-tone-families"
    assert args.tone_model == "ToneFamily"
