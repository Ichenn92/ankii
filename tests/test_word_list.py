import sys
from types import SimpleNamespace

import pytest

from ankii.settings import DEFAULT_PROFILE
from ankii.word_list import generate_word_list_review

TAGS = [
    "part_of_speech::expression",
    "topic::communication",
    "register::neutral",
    "level::A1",
]


def _install_fake_openai(monkeypatch, cards):
    class FakeResponses:
        def parse(self, *, text_format, **kwargs):
            assert kwargs["model"] == "test-model"
            assert kwargs["store"] is False
            return SimpleNamespace(output_parsed=text_format(cards=cards))

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))


def _card(index: int, word: str, meaning: str) -> dict[str, object]:
    return {
        "index": index,
        "word": word,
        "meaning": meaning,
        "example_target": f"Example with {word}.",
        "example_native": f"Example meaning {meaning}.",
        "tags": TAGS,
        "explanation": "Useful everyday vocabulary.",
    }


def test_generate_word_list_review_builds_import_ready_shape(monkeypatch) -> None:
    _install_fake_openai(
        monkeypatch,
        [_card(0, "xin chào", "hello"), _card(1, "tạm biệt", "goodbye")],
    )

    review = generate_word_list_review(
        ["xin chào", "goodbye"], "Class words", "test-model"
    )

    assert review["review_kind"] == "generated_word_list"
    assert review["lesson"]["title"] == "Class words"
    assert [card["word"] for card in review["cards"]] == ["xin chào", "tạm biệt"]
    assert all(card["approved"] is False for card in review["cards"])
    assert all(str(card["import_id"]).startswith("ankii:") for card in review["cards"])
    assert "source::word-list" in review["cards"][0]["tags"]
    assert DEFAULT_PROFILE.language_tag in review["cards"][0]["tags"]


def test_generate_word_list_review_rejects_missing_indexes(monkeypatch) -> None:
    _install_fake_openai(monkeypatch, [_card(0, "xin chào", "hello")])

    with pytest.raises(RuntimeError, match="expected 2"):
        generate_word_list_review(["xin chào", "goodbye"], "Words", "test-model")


def test_generate_word_list_review_rejects_invalid_taxonomy(monkeypatch) -> None:
    card = _card(0, "xin chào", "hello")
    card["tags"] = ["topic::food"] * 4
    _install_fake_openai(monkeypatch, [card])

    with pytest.raises(RuntimeError, match="invalid tags"):
        generate_word_list_review(["xin chào"], "Words", "test-model")
