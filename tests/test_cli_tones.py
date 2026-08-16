from ankii import cli
from ankii.tone_family import (
    TONE_NAMES,
    ToneEntry,
    ToneFamily,
    ToneSense,
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
            "addNote": 123,
            "addNotes": [201, 202, 203, 204, 205, 206],
        }[action]

    answers = iter(["IMPORT"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "generate_tone_family", lambda *_args: _family())
    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(cli, "setup_tone_family_model", lambda _model: True)
    monkeypatch.setattr(cli, "setup_vocabulary_tone_link", lambda _model: None)

    assert cli.run_tone_import(_family(), "Vietnamese", "ToneFamily", "Vocabulary") == 0
    assert [action for action, _kwargs in actions].count("findNotes") == 6
    assert [action for action, _kwargs in actions][-2:] == ["addNote", "addNotes"]


def test_tones_blocks_existing_family_before_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        cli,
        "invoke",
        lambda action, **_kwargs: {
            "deckNames": ["Vietnamese"],
            "modelNames": ["ToneFamily", "Vocabulary"],
            "findNotes": [99],
        }[action],
    )
    try:
        cli.run_tone_import(_family(), "Vietnamese", "ToneFamily", "Vocabulary")
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate was not rejected")


def test_tones_links_unique_existing_vocabulary_without_overwriting(monkeypatch) -> None:
    actions = []

    def fake_invoke(action, **kwargs):
        actions.append((action, kwargs))
        if action == "deckNames":
            return ["Vietnamese"]
        if action == "modelNames":
            return ["Vocabulary"]
        if action == "modelFieldNames":
            return ["Vietnamese", "English", "Tone Family"]
        if action == "findNotes":
            return [10]
        if action == "notesInfo":
            return [
                {
                    "noteId": 10,
                    "fields": {
                        "Vietnamese": {"value": "ma"},
                        "English": {"value": "existing meaning"},
                        "Tone Family": {"value": ""},
                    },
                    "tags": ["keep-me"],
                }
            ]
        if action == "addNote":
            return 123
        if action in {"updateNoteFields", "addTags"}:
            return None
        raise AssertionError(action)

    answers = iter(["IMPORT"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "generate_tone_family", lambda *_args: _single_entry_family())
    monkeypatch.setattr(cli, "invoke", fake_invoke)
    monkeypatch.setattr(cli, "setup_tone_family_model", lambda _model: True)
    monkeypatch.setattr(cli, "setup_vocabulary_tone_link", lambda _model: None)

    assert (
        cli.run_tone_import(_single_entry_family(), "Vietnamese", "ToneFamily", "Vocabulary") == 0
    )
    assert not any(action == "addNotes" for action, _kwargs in actions)
    update = next(kwargs for action, kwargs in actions if action == "updateNoteFields")
    assert set(update["note"]["fields"]) == {"Tone Family"}


def test_tones_rolls_back_parent_when_vocabulary_add_fails(monkeypatch) -> None:
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
        if action == "addNote":
            return 123
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
    monkeypatch.setattr(cli, "setup_tone_family_model", lambda _model: True)
    monkeypatch.setattr(cli, "setup_vocabulary_tone_link", lambda _model: None)

    try:
        cli.run_tone_import(_single_entry_family(), "Vietnamese", "ToneFamily", "Vocabulary")
    except RuntimeError as exc:
        assert "failed to add" in str(exc)
    else:
        raise AssertionError("failed child insertion was not reported")
    assert deleted == [123]
