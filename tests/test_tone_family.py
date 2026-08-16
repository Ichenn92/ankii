import sys
import unicodedata
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ankii.tone_family import (
    TONE_NAMES,
    VOCABULARY_LINK_FIELD,
    ToneEntry,
    ToneFamily,
    ToneSense,
    build_tone_family_note,
    build_tone_vocabulary_note,
    generate_tone_family,
    normalize_syllable,
    setup_tone_family_model,
    setup_vocabulary_tone_link,
    tone_family_fields,
    tone_family_from_review,
    tone_family_link,
    tone_family_templates,
    tone_family_to_review,
    tone_variants,
)


def test_normalize_and_generate_ma_family() -> None:
    assert normalize_syllable("  MÃ  ") == "ma"
    assert normalize_syllable(unicodedata.normalize("NFD", "mạ")) == "ma"
    assert tone_variants("má") == {
        "level": "ma",
        "acute": "má",
        "grave": "mà",
        "hook": "mả",
        "tilde": "mã",
        "dot": "mạ",
    }


@pytest.mark.parametrize(
    ("base", "acute", "hook", "dot"),
    [
        ("mươn", "mướn", "mưởn", "mượn"),
        ("hoa", "hóa", "hỏa", "họa"),
        ("huy", "húy", "hủy", "hụy"),
        ("quy", "quý", "quỷ", "quỵ"),
        ("gia", "giá", "giả", "giạ"),
        ("toan", "toán", "toản", "toạn"),
    ],
)
def test_tone_placement(base: str, acute: str, hook: str, dot: str) -> None:
    variants = tone_variants(base)
    assert variants["acute"] == acute
    assert variants["hook"] == hook
    assert variants["dot"] == dot


@pytest.mark.parametrize("value", ["", "xin chao", "ma2", "đ", "ma!"])
def test_invalid_syllables_are_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_syllable(value)


def _generated_entries() -> list[SimpleNamespace]:
    forms = tone_variants("ma")
    result = []
    for tone in TONE_NAMES:
        common = tone != "tilde"
        result.append(
            SimpleNamespace(
                tone=tone,
                form=forms[tone],
                senses=(
                    [
                        SimpleNamespace(
                            meaning=f"meaning {tone}",
                            part_of_speech="noun",
                            example_vn=f"Đây là {forms[tone]}.",
                            example_en=f"This is {tone}.",
                        )
                    ]
                    if common
                    else []
                ),
                usage_note="rare" if not common else "",
                common=common,
                tags=(
                    [
                        "part_of_speech::noun",
                        "topic::other",
                        "register::neutral",
                        "level::A1",
                    ]
                    if common
                    else []
                ),
            )
        )
    return result


def test_generate_tone_family_uses_and_validates_structured_response(monkeypatch) -> None:
    captured = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=SimpleNamespace(entries=_generated_entries(), explanation="Curated.")
            )

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    family = generate_tone_family("mã", "test-model")

    assert family.base == "ma"
    assert len(family.entries) == 6
    assert family.entries[4].common is False
    assert captured["store"] is False
    assert captured["model"] == "test-model"


def test_generate_rejects_ai_spelling_change(monkeypatch) -> None:
    entries = _generated_entries()
    entries[1].form = "wrong"

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = SimpleNamespace(
                parse=lambda **_kwargs: SimpleNamespace(
                    output_parsed=SimpleNamespace(entries=entries, explanation="")
                )
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    with pytest.raises(RuntimeError, match="unexpected acute form"):
        generate_tone_family("ma", "test-model")


def _family() -> ToneFamily:
    forms = tone_variants("ma")
    return ToneFamily(
        base="ma",
        model="test-model",
        explanation="AI <note>",
        entries=[
            ToneEntry(
                tone=tone,
                form=forms[tone],
                senses=(
                    [ToneSense("ghost & spirit", "noun", "Con ma ở đây.", "The ghost is here.")]
                    if tone == "level"
                    else []
                ),
                usage_note="rare" if tone != "level" else "",
                common=tone == "level",
                tags=(
                    [
                        "part_of_speech::noun",
                        "topic::other",
                        "register::neutral",
                        "level::A1",
                    ]
                    if tone == "level"
                    else []
                ),
            )
            for tone in TONE_NAMES
        ],
    )


def test_templates_make_one_recap_card_with_examples() -> None:
    templates = tone_family_templates()
    assert list(templates) == ["Family Recap"]
    back = templates["Family Recap"]["Back"]
    assert "{{^Tilde Enabled}}tone-muted" in back
    assert "{{Level Example VN}}" in back
    assert "{{Dialect Note}}" in back


def test_build_note_escapes_fields_and_enables_common_forms() -> None:
    note = build_tone_family_note(_family(), "Vietnamese", "ToneFamily")
    assert note["fields"]["Level Meaning"] == "ghost &amp; spirit"
    assert note["fields"]["AI Explanation"] == "AI &lt;note&gt;"
    assert note["fields"]["Level Enabled"] == "1"
    assert note["fields"]["Acute Enabled"] == ""
    assert "dialect::southern" in note["tags"]


@patch("ankii.tone_family.invoke")
def test_setup_creates_tone_family_model(invoke) -> None:
    invoke.side_effect = [[], None]
    assert setup_tone_family_model() is True
    create = invoke.mock_calls[-1]
    assert create.args == ("createModel",)
    assert create.kwargs["modelName"] == "ToneFamily"
    assert create.kwargs["inOrderFields"] == tone_family_fields()
    assert len(create.kwargs["cardTemplates"]) == 1


@patch("ankii.tone_family.invoke")
def test_setup_refreshes_managed_model_and_preserves_unrelated_template(invoke) -> None:
    fields = tone_family_fields()
    invoke.side_effect = [
        ["ToneFamily"],
        fields,
        {"css": "custom{}\n/* yhw2anki tone-family */old/* /yhw2anki tone-family */"},
        {
            "Custom": {"Front": "x", "Back": "y"},
            "Ngang Recall": {"Front": "old", "Back": "old"},
        },
        None,
        None,
        None,
    ]
    assert setup_tone_family_model() is False
    assert any(item.args == ("modelTemplateAdd",) for item in invoke.mock_calls)
    remove = next(item for item in invoke.mock_calls if item.args == ("modelTemplateRemove",))
    assert remove.kwargs["templateName"] == "Ngang Recall"
    assert not any(item.args == ("updateModelTemplates",) for item in invoke.mock_calls)


@patch("ankii.tone_family.invoke")
def test_setup_refuses_unmanaged_name_collision(invoke) -> None:
    invoke.side_effect = [["ToneFamily"], ["Front"], {"css": ".card{}"}]
    with pytest.raises(ValueError, match="not managed"):
        setup_tone_family_model()


def test_build_vocabulary_note_is_self_contained_and_links_parent() -> None:
    family = _family()
    entry = family.entries[0]
    fields = {
        "Vietnamese",
        "English",
        "Example VN",
        "Example EN",
        "AIExplanation",
        "Source",
        "Lesson",
        VOCABULARY_LINK_FIELD,
    }
    note = build_tone_vocabulary_note(entry, family, "Vietnamese", "Vocabulary", fields, 123)
    assert note["fields"]["Vietnamese"] == "ma"
    assert "m&#" not in note["fields"]["English"]
    assert "nid%3A123" in note["fields"][VOCABULARY_LINK_FIELD]
    assert "tone_family::ma" in note["tags"]
    assert "mà" not in str(note["fields"])


def test_parent_link_is_ankimobile_search_link() -> None:
    assert tone_family_link("ma", 42) == (
        '<a href="anki://x-callback-url/search?query=nid%3A42">Tone family: ma</a>'
    )


def test_tone_family_review_round_trip_contains_vocabulary_cards() -> None:
    family = _family()
    review = tone_family_to_review(family)
    restored = tone_family_from_review(review)
    assert restored == family
    assert review["review_kind"] == "tone_family"
    assert [card["word"] for card in review["cards"]] == ["ma"]
    assert review["cards"][0]["approved"] is True


@patch("ankii.tone_family.invoke")
def test_setup_vocabulary_link_adds_field_and_managed_back_block(invoke) -> None:
    invoke.side_effect = [
        ["Vocabulary"],
        ["Vietnamese", "English"],
        None,
        {
            "Card": {
                "Front": "{{Vietnamese}}",
                "Back": (
                    "{{English}}\n<!-- yhw2anki tone-family link -->old"
                    "<!-- /yhw2anki tone-family link -->"
                ),
            }
        },
        None,
        {
            "css": (
                ".card{}\n/* yhw2anki tone-family link */old"
                "/* /yhw2anki tone-family link */"
            )
        },
        None,
    ]
    setup_vocabulary_tone_link()
    assert any(item.args == ("modelFieldAdd",) for item in invoke.mock_calls)
    update = next(item for item in invoke.mock_calls if item.args == ("updateModelTemplates",))
    updated_back = update.kwargs["model"]["templates"]["Card"]["Back"]
    assert "ankii tone-family link" in updated_back
    assert "yhw2anki tone-family link" not in updated_back
