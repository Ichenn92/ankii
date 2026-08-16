import sys
from types import SimpleNamespace

import pytest

from ankii.analyzer import (
    analyze_passage,
    known_anki_headwords,
    normalize_headword,
)

TAGS = [
    "part_of_speech::expression",
    "topic::communication",
    "register::informal",
    "level::B1",
]


def _parsed(example_vn: str = "Đừng có mơ.") -> SimpleNamespace:
    return SimpleNamespace(
        translation="Don't dream of it.",
        interpretation="A dismissive warning.",
        styles=["informal"],
        style_explanation="Common forceful spoken language.",
        grammar=[SimpleNamespace(pattern="đừng có", explanation="Negative imperative.")],
        candidates=[
            SimpleNamespace(
                card_type="vocabulary",
                word="đừng có mơ",
                meaning="don't even dream of it",
                example_vn=example_vn,
                example_en="Don't even dream of it.",
                rationale="A reusable emphatic refusal.",
                tags=TAGS,
                everyday_example_vn="Đừng có mơ đến chuyện nghỉ sớm hôm nay.",
                everyday_example_en="Don't dream of leaving early today.",
                simple_example_vn="Đừng mơ nữa.",
                simple_example_en="Stop dreaming.",
            )
        ],
    )


def test_analyze_passage_uses_structured_response(monkeypatch) -> None:
    captured = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_parsed=_parsed())

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    result = analyze_passage("Đừng có mơ.", "test-model")

    assert result.candidates[0].word == "đừng có mơ"
    assert result.candidates[0].card_type == "vocabulary"
    assert result.candidates[0].everyday_example_vn.startswith("Đừng có mơ")
    assert result.candidates[0].simple_example_vn == "Đừng mơ nữa."
    assert result.grammar[0][0] == "đừng có"
    assert captured["store"] is False


def test_analyze_passage_rejects_invented_example(monkeypatch) -> None:
    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=_parsed("Tôi đang mơ."))

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    with pytest.raises(RuntimeError, match="not found"):
        analyze_passage("Đừng có mơ.", "test-model")


def test_known_anki_headwords_normalizes_values(monkeypatch) -> None:
    def fake_invoke(action, **_params):
        return {
            "modelNames": ["Basic", "Vietnamese"],
            "modelFieldNames": ["Vietnamese", "English"],
            "findNotes": [12],
            "notesInfo": [{"fields": {"Vietnamese": {"value": " ĐỪNG   CÓ MƠ "}}}],
        }[action]

    monkeypatch.setattr("ankii.analyzer.invoke", fake_invoke)
    words, model = known_anki_headwords()

    assert words == {normalize_headword("đừng có mơ")}
    assert model == "Vietnamese"
