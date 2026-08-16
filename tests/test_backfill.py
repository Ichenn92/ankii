from pathlib import Path
from unittest.mock import call, patch

from ankii.note_type import backfill_examples


@patch("ankii.note_type.load_review")
@patch("ankii.note_type.invoke")
def test_backfill_fills_only_empty_matching_fields(invoke, load_review) -> None:
    load_review.return_value = {
        "lesson": {"source_url": "https://yourhomework.net/vocab/1"},
        "cards": [
            {
                "word": "thực đơn",
                "example_vn": "VN new",
                "example_en": "EN new",
            }
        ],
    }
    invoke.side_effect = [
        ["Vietnamese", "English", "Source", "Example VN", "Example EN"],
        [10],
        [
            {
                "noteId": 10,
                "fields": {
                    "Vietnamese": {"value": "thực đơn"},
                    "Source": {"value": "https://yourhomework.net/vocab/1"},
                    "Example VN": {"value": "Keep VN"},
                    "Example EN": {"value": ""},
                },
            }
        ],
        None,
    ]

    result = backfill_examples(Path("review.json"), "Vietnamese")

    assert result["notes_updated"] == 1
    assert call(
        "updateNoteFields", note={"id": 10, "fields": {"Example EN": "EN new"}}
    ) in invoke.mock_calls
