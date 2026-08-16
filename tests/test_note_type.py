from unittest.mock import call, patch

from ankii.note_type import (
    GRAMMAR_BACK,
    GRAMMAR_CSS,
    GRAMMAR_FIELDS,
    _close_unbalanced_css_blocks,
    setup_learning_models,
    setup_note_type,
)


def test_closes_inherited_css_before_managed_styles_are_appended() -> None:
    css = "@media (max-width: 480px) {\n.card { padding: 10px; }"

    repaired = _close_unbalanced_css_blocks(css)

    assert repaired.endswith("\n}")
    assert repaired.count("{") == repaired.count("}")


@patch("ankii.note_type.invoke")
def test_setup_learning_models_clones_migrates_and_creates_grammar(invoke) -> None:
    invoke.side_effect = [
        ["Vietnamese"],
        ["Vietnamese", "English", "Everyday Example VN", "Everyday Example EN"],
        {
            "Card": {
                "Front": "{{English}}",
                "Back": (
                    "{{Vietnamese}}\n<!-- yhw2anki examples -->duplicate"
                    "<!-- /yhw2anki examples -->\n"
                    "<!-- yhw2anki everyday examples -->old"
                    "<!-- /yhw2anki everyday examples -->"
                ),
            }
        },
        {
            "css": (
                ".card { color: #252525; }\n"
                "/* yhw2anki examples */duplicate/* /yhw2anki examples */"
            )
        },
        None,
        [10],
        [
            {
                "noteId": 10,
                "fields": {
                    "Vietnamese": {"value": "xin chào"},
                    "English": {"value": "hello"},
                },
                "tags": ["level::A1"],
            }
        ],
        None,
        None,
    ]

    result = setup_learning_models()

    assert result == {
        "vocabulary_created": 1,
        "notes_migrated": 1,
        "grammar_created": 1,
    }
    assert call(
        "updateNoteModel",
        note={
            "id": 10,
            "modelName": "Vocabulary",
            "fields": {"Target": "xin chào", "Native": "hello"},
            "tags": ["level::A1"],
        },
    ) in invoke.mock_calls
    grammar_call = invoke.mock_calls[-1]
    assert grammar_call.kwargs["modelName"] == "Grammar"
    assert grammar_call.kwargs["inOrderFields"] == list(GRAMMAR_FIELDS)
    vocabulary_call = next(
        item
        for item in invoke.mock_calls
        if item.args == ("createModel",) and item.kwargs["modelName"] == "Vocabulary"
    )
    assert vocabulary_call.kwargs["inOrderFields"] == [
        "Target",
        "Native",
        "Import ID",
    ]
    assert "everyday examples" not in vocabulary_call.kwargs["cardTemplates"][0]["Back"]
    assert vocabulary_call.kwargs["cardTemplates"][0]["Back"].count(
        "<!-- ankii examples -->"
    ) == 1
    assert "yhw2anki examples" not in vocabulary_call.kwargs["cardTemplates"][0]["Back"]
    assert "{{Example Target}}" in vocabulary_call.kwargs["cardTemplates"][0]["Back"]
    assert "ankii examples" not in vocabulary_call.kwargs["css"]


@patch("ankii.note_type.invoke")
def test_setup_adds_fields_migrates_without_overwrite_and_updates_templates(invoke) -> None:
    invoke.side_effect = [
        ["Vietnamese Vocabulary"],
        ["Vietnamese", "English", "Example"],
        None,
        None,
        None,
        [10, 11],
        [
            {"noteId": 10, "fields": {"Example": {"value": "Xin chào."}}},
            {
                "noteId": 11,
                "fields": {
                    "Example": {"value": "Legacy"},
                    "Example VN": {"value": "Keep me"},
                },
            },
        ],
        None,
        {"Card 1": {"Front": "{{Vietnamese}}", "Back": "{{English}}"}},
        None,
        {"css": ".card {}"},
        None,
    ]

    result = setup_note_type("Vietnamese Vocabulary")

    assert result == {
        "fields_added": 3,
        "notes_migrated": 1,
        "templates_updated": 1,
        "styling_updated": 1,
    }
    add_vn = call(
        "modelFieldAdd", modelName="Vietnamese Vocabulary", fieldName="Example VN"
    )
    add_en = call(
        "modelFieldAdd", modelName="Vietnamese Vocabulary", fieldName="Example EN"
    )
    assert add_vn in invoke.mock_calls
    assert add_en in invoke.mock_calls
    assert call(
        "updateNoteFields", note={"id": 10, "fields": {"Example VN": "Xin chào."}}
    ) in invoke.mock_calls


@patch("ankii.note_type.invoke")
def test_setup_renders_source_on_vocabulary_card_back(invoke) -> None:
    invoke.side_effect = [
        ["Vietnamese Vocabulary"],
        ["Vietnamese", "English", "Source", "Example VN", "Example EN"],
        None,
        {
            "Card 1": {
                "Front": "{{Vietnamese}}",
                "Back": (
                    "{{English}}\n<!-- ankii source -->"
                    '<div class="yhw-source">old</div>'
                    "<!-- /ankii source -->"
                ),
            }
        },
        None,
        {"css": ".card {}"},
        None,
    ]

    setup_note_type("Vietnamese Vocabulary")

    update = next(
        item for item in invoke.mock_calls if item.args == ("updateModelTemplates",)
    )
    back = update.kwargs["model"]["templates"]["Card 1"]["Back"]
    assert "{{#Source}}" in back
    assert "{{Source}}" in back
    assert '<div class="yhw-source">old</div>' not in back


def test_grammar_card_back_renders_source() -> None:
    assert "{{#Source}}" in GRAMMAR_BACK
    assert "{{Source}}" in GRAMMAR_BACK


def test_source_card_supports_service_icons_and_generic_open_link() -> None:
    assert "yhw-source-card" in GRAMMAR_BACK
    assert "youtube.com" in GRAMMAR_BACK
    assert "spotify.com" in GRAMMAR_BACK
    assert "spotify:${parts[0]}:${parts[1]}" in GRAMMAR_BACK
    assert "youtube://watch" in GRAMMAR_BACK
    assert "makeLink(url, 'Web'" in GRAMMAR_BACK
    assert "makeLink(url, 'Open'" in GRAMMAR_BACK
    assert ".yhw-source-card" in GRAMMAR_CSS


@patch("ankii.note_type.invoke")
def test_setup_is_idempotent(invoke) -> None:
    invoke.side_effect = [
        ["Vietnamese Vocabulary"],
        [
            "Vietnamese",
            "English",
            "Example VN",
            "Example EN",
            "Everyday Example VN",
            "Everyday Example EN",
        ],
        None,
        {
            "Card 1": {
                "Front": "front",
                "Back": "<!-- ankii examples --> <!-- ankii everyday examples -->",
            }
        },
        {"css": "/* ankii examples */ /* ankii everyday examples */"},
    ]

    result = setup_note_type("Vietnamese Vocabulary")

    assert result == {
        "fields_added": 1,
        "notes_migrated": 0,
        "templates_updated": 0,
        "styling_updated": 0,
    }
