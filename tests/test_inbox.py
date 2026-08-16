from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from ankii.inbox import append_card, archive_imported_cards, load_or_create_inbox
from ankii.review import load_review


def card(word: str) -> dict[str, object]:
    return {
        "word": word,
        "meaning": "meaning",
        "tags": ["source::manual"],
        "approved": True,
        "skip": False,
    }


def test_append_creates_and_reuses_manual_inbox(tmp_path: Path) -> None:
    path = tmp_path / "inbox.review.json"

    assert append_card(path, card("một")) == 1
    assert append_card(path, card("hai")) == 2

    inbox = load_or_create_inbox(path)
    assert inbox["review_kind"] == "manual_inbox"
    assert [item["word"] for item in inbox["cards"]] == ["một", "hai"]


def test_archive_moves_only_successes_and_keeps_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "inbox.review.json"
    append_card(path, card("một"))
    append_card(path, card("hai"))
    review = load_review(path)

    archive_path = archive_imported_cards(
        path,
        review,
        [(0, 123)],
        "Vietnamese",
        "Vietnamese Vocabulary",
        imported_at=datetime(2026, 8, 9, 12, 30, tzinfo=UTC),
    )

    assert archive_path == tmp_path / "archive/inbox-20260809-123000.imported.json"
    assert [item["word"] for item in load_review(path)["cards"]] == ["hai"]
    archived = load_review(archive_path)
    assert archived["cards"][0]["import"]["anki_note_id"] == 123


def test_archive_failure_leaves_inbox_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "inbox.review.json"
    append_card(path, card("một"))
    review = load_review(path)

    with (
        patch("ankii.inbox.save_review_atomic", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        archive_imported_cards(path, review, [(0, 123)], "Deck", "Model")

    assert [item["word"] for item in load_review(path)["cards"]] == ["một"]
