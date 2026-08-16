from pathlib import Path

from ankii.review import create_review, load_review, replace_ai_tags, save_review
from ankii.yourhomework import Lesson, VocabularyItem


def sample_lesson() -> Lesson:
    return Lesson(
        public_id="123",
        title="Test lesson",
        source_language="Vietnamese",
        source_url="https://yourhomework.net/vocab/123",
        items=[VocabularyItem("xin chào", "hello", "", "", "")],
    )


def test_review_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "review.json"
    save_review(create_review(sample_lesson()), path)

    review = load_review(path)

    assert review["lesson"]["public_id"] == "123"
    assert review["cards"][0]["tags"] == ["source::yourhomework", "lesson::123"]
    assert review["cards"][0]["approved"] is False
    assert review["cards"][0]["import_id"].startswith("ankii:")


def test_replace_ai_tags_preserves_source_tags() -> None:
    result = replace_ai_tags(
        ["source::yourhomework", "topic::old", "custom"],
        ["topic::people", "level::A1", "not-allowed"],
    )

    assert result == ["source::yourhomework", "custom", "topic::people", "level::A1"]
