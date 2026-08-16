import pytest

from ankii.importer import (
    FIELD_DEFAULTS,
    GRAMMAR_FIELDS,
    build_grammar_note,
    build_note,
    detect_card_type,
    infer_field_names,
    prepare_import,
)
from ankii.review import load_review


def test_infer_fields_for_existing_vietnamese_model() -> None:
    fields = [
        "Vietnamese",
        "English",
        "Source",
        "Audio",
        "Components",
        "Notes",
        "Visual Media",
        "Example",
    ]

    result = infer_field_names(fields)

    assert result["vietnamese"] == "Vietnamese"
    assert result["english"] == "English"
    assert result["example_vn"] == "Example"
    assert result["explanation"] == "Notes"
    assert result["image"] == "Visual Media"


def test_build_note_maps_fields_and_picture() -> None:
    card = {
        "word": "thực đơn",
        "meaning": "menu",
        "example_vn": "Cho tôi xem thực đơn.\nTôi đang xem thực đơn.",
        "example_en": "Show me the menu.\nI am looking at the menu.",
        "image_url": "https://example.com/menu.png",
        "tags": ["source::yourhomework"],
        "ai_explanation": "A restaurant noun.",
    }
    lesson = {"source_url": "https://yourhomework.net/vocab/123", "title": "Lesson"}

    note = build_note(
        card,
        lesson,
        "Vietnamese",
        "Vietnamese Vocabulary",
        set(FIELD_DEFAULTS.values()),
        FIELD_DEFAULTS,
    )

    assert note["fields"]["Vietnamese"] == "thực đơn"
    assert note["fields"]["English"] == "menu"
    assert note["fields"]["Example VN"] == (
        "Cho tôi xem thực đơn.<br>Tôi đang xem thực đơn."
    )
    assert note["fields"]["Example EN"] == (
        "Show me the menu.<br>I am looking at the menu."
    )
    assert note["picture"]["fields"] == ["Image"]
    assert note["options"]["allowDuplicate"] is False


def test_build_note_omits_optional_fields_missing_from_model() -> None:
    card = {"word": "ngon", "meaning": "delicious", "tags": [], "image_url": ""}

    note = build_note(
        card,
        {},
        "Default",
        "Basic",
        {"Vietnamese", "English"},
        FIELD_DEFAULTS,
    )

    assert note["fields"] == {"Vietnamese": "ngon", "English": "delicious"}
    assert "picture" not in note


def test_manual_card_uses_image_credit_as_source() -> None:
    card = {
        "word": "mèo",
        "meaning": "cat",
        "tags": ["source::manual"],
        "image_url": "https://upload.wikimedia.org/cat.jpg",
        "image_source_url": "https://commons.wikimedia.org/wiki/File:Cat.jpg",
        "image_attribution": "Example Author — CC BY-SA 4.0",
    }

    note = build_note(
        card,
        {"public_id": "manual-inbox", "title": "Manual vocabulary"},
        "Vietnamese",
        "Vietnamese Vocabulary",
        {"Vietnamese", "English", "Source", "Image"},
        FIELD_DEFAULTS,
    )

    assert "Example Author — CC BY-SA 4.0" in note["fields"]["Source"]
    assert "commons.wikimedia.org" in note["fields"]["Source"]


def test_analysis_card_uses_title_and_url_as_source() -> None:
    card = {
        "word": "mơ",
        "meaning": "dream",
        "tags": ["source::analysis"],
        "source_title": "A song",
        "source_url": "https://example.com/song",
    }

    note = build_note(
        card,
        {"public_id": "manual-inbox", "title": "Manual vocabulary"},
        "Vietnamese",
        "Vietnamese Vocabulary",
        {"Vietnamese", "English", "Source"},
        FIELD_DEFAULTS,
    )

    assert note["fields"]["Source"] == "A song — https://example.com/song"


def test_build_grammar_note_uses_dedicated_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        "ankii.importer.invoke",
        lambda action, **_params: list(GRAMMAR_FIELDS.values())
        if action == "modelFieldNames"
        else None,
    )
    card = {
        "word": "có … thì …",
        "meaning": "Creates an emphatic conditional.",
        "example_vn": "Anh có thương thì qua.\nCó thời gian thì gọi tôi nhé.",
        "example_en": "If you care, come over.\nIf you have time, call me.",
        "source_title": "A song",
        "tags": ["source::analysis", "card_type::grammar"],
        "ai_explanation": "A reusable conditional frame.",
    }

    note = build_grammar_note(card, {}, "Vietnamese", "Grammar")

    assert note["modelName"] == "Grammar"
    assert note["fields"]["Grammar"] == "có … thì …"
    assert note["fields"]["Explanation"] == "Creates an emphatic conditional."
    assert note["fields"]["Example VN"] == (
        "Anh có thương thì qua.<br>Có thời gian thì gọi tôi nhé."
    )


def test_detect_card_type_supports_json_field_and_legacy_tag() -> None:
    assert detect_card_type({"card_type": "grammar", "tags": []}) == "grammar"
    assert detect_card_type({"tags": ["card_type::grammar"]}) == "grammar"
    assert detect_card_type({"tags": ["card_type::vocabulary"]}) == "vocabulary"


def test_detect_card_type_rejects_missing_type() -> None:
    with pytest.raises(ValueError, match="missing card_type"):
        detect_card_type({"word": "test", "tags": []})


@pytest.mark.parametrize("card_type", ["sentence", "", None, 42])
def test_detect_card_type_rejects_unknown_explicit_type(card_type) -> None:
    card = {"word": "test", "tags": []}
    if card_type is not None:
        card["card_type"] = card_type
    with pytest.raises(ValueError, match="unknown card_type|missing card_type"):
        detect_card_type(card)


def test_detect_card_type_rejects_conflicting_json_data() -> None:
    with pytest.raises(ValueError, match="conflicting card types"):
        detect_card_type(
            {"word": "test", "card_type": "grammar", "tags": ["card_type::vocabulary"]}
        )


def test_prepare_import_routes_each_mixed_card_to_its_model(
    monkeypatch, tmp_path
) -> None:
    review_path = tmp_path / "mixed.review.json"
    review_path.write_text(
        """{
          "review_version": 1,
          "lesson": {},
          "cards": [
            {"word":"xin chào","meaning":"hello","card_type":"vocabulary",
             "tags":[],"approved":true,"skip":false},
            {"word":"có … thì …","meaning":"conditional","card_type":"grammar",
             "tags":[],"approved":true,"skip":false}
          ]
        }""",
        encoding="utf-8",
    )

    def fake_invoke(action, **params):
        if action == "deckNames":
            return ["Vietnamese"]
        if action == "modelNames":
            return ["Vocabulary", "Grammar"]
        if action == "modelFieldNames":
            if params["modelName"] == "Grammar":
                return list(GRAMMAR_FIELDS.values())
            return list(FIELD_DEFAULTS.values())
        if action == "canAddNotes":
            return [True, True]
        raise AssertionError(action)

    monkeypatch.setattr("ankii.importer.invoke", fake_invoke)
    _review, notes, can_add = prepare_import(
        review_path, "Vietnamese", "Vocabulary", FIELD_DEFAULTS
    )

    assert [note["modelName"] for note in notes] == ["Vocabulary", "Grammar"]
    assert can_add == [True, True]


def test_prepare_import_upgrades_legacy_manual_card(monkeypatch, tmp_path) -> None:
    review_path = tmp_path / "inbox.review.json"
    review_path.write_text(
        """{
          "review_version": 1,
          "review_kind": "manual_inbox",
          "lesson": {},
          "cards": [
            {"word":"xin chào","meaning":"hello",
             "tags":["source::manual"],"approved":true,"skip":false}
          ]
        }""",
        encoding="utf-8",
    )

    def fake_invoke(action, **_params):
        if action == "deckNames":
            return ["Vietnamese"]
        if action == "modelNames":
            return ["Vocabulary"]
        if action == "modelFieldNames":
            return list(FIELD_DEFAULTS.values())
        if action == "canAddNotes":
            return [True]
        raise AssertionError(action)

    monkeypatch.setattr("ankii.importer.invoke", fake_invoke)
    review, notes, _can_add = prepare_import(
        review_path, "Vietnamese", "Vocabulary", FIELD_DEFAULTS
    )

    assert "card_type::vocabulary" in review["cards"][0]["tags"]
    assert notes[0]["modelName"] == "Vocabulary"
    assert "card_type::vocabulary" in load_review(review_path)["cards"][0]["tags"]


def test_prepare_import_upgrades_legacy_yourhomework_card(monkeypatch, tmp_path) -> None:
    review_path = tmp_path / "lesson.review.json"
    review_path.write_text(
        """{
          "review_version": 2,
          "lesson": {"source_language": "vi"},
          "cards": [
            {"word":"yêu cầu gì thêm","meaning":"anything else",
             "tags":["source::yourhomework"],"approved":true,"skip":false}
          ]
        }""",
        encoding="utf-8",
    )

    def fake_invoke(action, **_params):
        if action == "deckNames":
            return ["Vietnamese"]
        if action == "modelNames":
            return ["Vocabulary"]
        if action == "modelFieldNames":
            return list(FIELD_DEFAULTS.values())
        if action == "canAddNotes":
            return [True]
        raise AssertionError(action)

    monkeypatch.setattr("ankii.importer.invoke", fake_invoke)
    review, notes, _can_add = prepare_import(
        review_path, "Vietnamese", "Vocabulary", FIELD_DEFAULTS
    )

    assert "card_type::vocabulary" in review["cards"][0]["tags"]
    assert notes[0]["modelName"] == "Vocabulary"
    assert "card_type::vocabulary" in load_review(review_path)["cards"][0]["tags"]
