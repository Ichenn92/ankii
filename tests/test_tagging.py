import sys
from pathlib import Path
from types import SimpleNamespace

from ankii.review import create_review, load_review, save_review
from ankii.tagging import tag_review
from ankii.yourhomework import Lesson, VocabularyItem


def test_tag_review_updates_local_file(monkeypatch, tmp_path: Path) -> None:
    lesson = Lesson(
        public_id="123",
        title="Test",
        source_language="Vietnamese",
        source_url="https://yourhomework.net/vocab/123",
        items=[VocabularyItem("ngon", "delicious", "Món này ngon.", "This is delicious.", "")],
    )
    path = tmp_path / "review.json"
    save_review(create_review(lesson), path)

    class FakeResponses:
        def parse(self, *, text_format, **kwargs):
            assert kwargs["store"] is False
            parsed = text_format(
                cards=[
                    {
                        "index": 0,
                        "tags": [
                            "part_of_speech::adjective",
                            "topic::food",
                            "register::neutral",
                            "level::A1",
                        ],
                        "explanation": "Common adjective for food quality.",
                    }
                ]
            )
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    assert tag_review(path, "test-model") == 1
    card = load_review(path)["cards"][0]
    assert "part_of_speech::adjective" in card["tags"]
    assert card["ai_explanation"] == "Common adjective for food quality."


def test_tag_review_rejects_four_tags_from_same_dimension(monkeypatch, tmp_path: Path) -> None:
    lesson = Lesson(
        public_id="123",
        title="Test",
        source_language="Vietnamese",
        source_url="https://yourhomework.net/vocab/123",
        items=[VocabularyItem("ngon", "delicious", "", "", "")],
    )
    path = tmp_path / "review.json"
    save_review(create_review(lesson), path)

    class FakeResponses:
        def parse(self, *, text_format, **kwargs):
            return SimpleNamespace(
                output_parsed=text_format(
                    cards=[
                        {
                            "index": 0,
                            "tags": [
                                "topic::food",
                                "topic::drink",
                                "topic::restaurant",
                                "topic::daily_life",
                            ],
                            "explanation": "Invalid dimensions.",
                        }
                    ]
                )
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    try:
        tag_review(path, "test-model")
    except RuntimeError as exc:
        assert "invalid tags" in str(exc)
    else:
        raise AssertionError("Invalid tag dimensions were accepted")
