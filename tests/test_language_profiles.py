import json
from pathlib import Path

from ankii.analyzer import known_anki_headwords
from ankii.importer import GENERIC_FIELD_DEFAULTS, build_note
from ankii.review import load_review, save_review, validate_review_profile
from ankii.settings import LanguageProfile

FRENCH = LanguageProfile("french", "French", "English", "French", "A1", "B2")


def test_generic_note_fields_are_used_for_french() -> None:
    note = build_note(
        {
            "word": "bonjour",
            "meaning": "hello",
            "example_target": "Bonjour, Marie.",
            "example_native": "Hello, Marie.",
            "tags": [FRENCH.language_tag],
        },
        {},
        FRENCH.deck,
        "Vocabulary",
        set(GENERIC_FIELD_DEFAULTS.values()),
        GENERIC_FIELD_DEFAULTS,
    )

    assert note["deckName"] == "French"
    assert note["fields"]["Target"] == "bonjour"
    assert note["fields"]["Example Native"] == "Hello, Marie."


def test_known_words_are_scoped_to_profile_deck(monkeypatch) -> None:
    queries: list[str] = []

    def fake_invoke(action, **params):
        if action == "modelNames":
            return ["Vocabulary"]
        if action == "modelFieldNames":
            return ["Target", "Native"]
        if action == "findNotes":
            queries.append(params["query"])
            return [1]
        if action == "notesInfo":
            return [{"fields": {"Target": {"value": "bonjour"}}}]
        raise AssertionError(action)

    monkeypatch.setattr("ankii.analyzer.invoke", fake_invoke)

    words, _model = known_anki_headwords(FRENCH)

    assert words == {"bonjour"}
    assert queries == ['note:"Vocabulary" deck:"French"']


def test_version_one_review_is_saved_with_neutral_examples(tmp_path: Path) -> None:
    path = tmp_path / "legacy.review.json"
    data = {
        "review_version": 1,
        "lesson": {},
        "cards": [
            {
                "word": "bonjour",
                "meaning": "hello",
                "example_vn": "Bonjour.",
                "example_en": "Hello.",
                "tags": [],
                "approved": True,
                "skip": False,
            }
        ],
    }

    save_review(data, path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert raw["review_version"] == 2
    assert raw["cards"][0]["example_target"] == "Bonjour."
    assert "example_vn" not in raw["cards"][0]
    assert load_review(path)["cards"][0]["example_vn"] == "Bonjour."


def test_iso_language_code_matches_profile_display_name() -> None:
    vietnamese = LanguageProfile(
        "vietnamese", "Vietnamese", "English", "Vietnamese", "A1", "B2"
    )

    validate_review_profile({"lesson": {"source_language": "vi"}}, vietnamese)
