import json
from pathlib import Path

from ankii import maintenance
from ankii.review import save_review
from ankii.tone_family import (
    TONE_NAMES,
    ToneEntry,
    ToneFamily,
    ToneSense,
    tone_family_to_review,
    tone_variants,
)


def _note(
    note_id: int, word: str, source: str = "", import_id: str = ""
) -> dict[str, object]:
    return {
        "noteId": note_id,
        "fields": {
            "Vietnamese": {"value": word},
            "Source": {"value": source},
            "Import ID": {"value": import_id},
        },
        "tags": ["source::manual", "custom"],
    }


def _review(path: Path, word: str, source: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "review_version": 1,
                "lesson": {"source_url": source, "title": "Lesson"},
                "cards": [
                    {
                        "word": word,
                        "meaning": "hello",
                        "tags": ["source::yourhomework", "topic::communication"],
                        "approved": True,
                        "skip": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_retag_preserves_non_taxonomy_tags(monkeypatch) -> None:
    monkeypatch.setattr(maintenance, "notes_for_model", lambda _model: [_note(7, "xin chào")])
    monkeypatch.setattr(
        maintenance,
        "invoke",
        lambda action, **_kwargs: (
            ["Vietnamese", "English", "Source"] if action == "modelFieldNames" else None
        ),
    )
    monkeypatch.setattr(
        maintenance,
        "suggest_card_tags",
        lambda _card, _model: (
            [
                "part_of_speech::expression",
                "topic::communication",
                "register::neutral",
                "level::A1",
            ],
            "greeting",
        ),
    )

    change = maintenance.retag_notes("Vietnamese", "test-model")[0]

    assert change["new_tags"][:2] == ["source::manual", "custom"]
    assert "topic::communication" in change["new_tags"]


def test_reimport_matches_unique_word(monkeypatch, tmp_path: Path) -> None:
    _review(tmp_path / "archive/1.review.json", "xin chào", "https://lesson")
    monkeypatch.setattr(maintenance, "notes_for_model", lambda _model: [_note(7, "xin chào")])
    monkeypatch.setattr(
        maintenance,
        "invoke",
        lambda action, **_kwargs: (
            ["Vietnamese", "English", "Source"] if action == "modelFieldNames" else None
        ),
    )

    changes, stats = maintenance.prepare_reimport(tmp_path, "Vietnamese", "Vietnamese")

    assert [change["id"] for change in changes] == [7]
    assert stats["matched"] == 1


def test_reimport_prefers_import_id_when_word_changed(monkeypatch, tmp_path: Path) -> None:
    _review(tmp_path / "archive/1.review.json", "new spelling", "https://lesson")
    review = json.loads((tmp_path / "archive/1.review.json").read_text())
    review["cards"][0]["import_id"] = "yhw2anki:stable"
    (tmp_path / "archive/1.review.json").write_text(json.dumps(review))
    monkeypatch.setattr(
        maintenance,
        "notes_for_model",
        lambda _model: [_note(7, "old spelling", import_id="yhw2anki:stable")],
    )
    monkeypatch.setattr(
        maintenance,
        "invoke",
        lambda action, **_kwargs: (
            ["Vietnamese", "English", "Source", "Import ID"]
            if action == "modelFieldNames"
            else None
        ),
    )

    changes, stats = maintenance.prepare_reimport(
        tmp_path, "Vocabulary", "Vietnamese"
    )

    assert [change["id"] for change in changes] == [7]
    assert changes[0]["fields"]["Import ID"] == "yhw2anki:stable"
    assert stats["matched"] == 1


def test_reimport_skips_duplicate_review_records(monkeypatch, tmp_path: Path) -> None:
    _review(tmp_path / "archive/1.review.json", "xin chào")
    _review(tmp_path / "archive/2.review.json", "xin chào")
    monkeypatch.setattr(maintenance, "notes_for_model", lambda _model: [_note(7, "xin chào")])
    monkeypatch.setattr(
        maintenance,
        "invoke",
        lambda action, **_kwargs: (
            ["Vietnamese", "English", "Source"] if action == "modelFieldNames" else None
        ),
    )

    changes, stats = maintenance.prepare_reimport(tmp_path, "Vietnamese", "Vietnamese")

    assert changes == []
    assert stats["ambiguous"] == 2


def test_reimport_updates_embedded_tone_family_on_vocabulary(monkeypatch, tmp_path: Path) -> None:
    forms = tone_variants("ma")
    family = ToneFamily(
        "ma",
        [
            ToneEntry(
                tone,
                forms[tone],
                [ToneSense("ghost", "noun", "Con ma.", "A ghost.")] if tone == "level" else [],
                "rare" if tone != "level" else "",
                tone == "level",
                [
                    "part_of_speech::noun",
                    "topic::other",
                    "register::neutral",
                    "level::A1",
                ]
                if tone == "level"
                else [],
            )
            for tone in TONE_NAMES
        ],
        "updated",
        "test-model",
    )
    save_review(tone_family_to_review(family), tmp_path / "ma.review.json")
    vocabulary = _note(7, "ma")
    parent = {
        "noteId": 9,
        "fields": {"Base": {"value": "ma"}},
        "tags": ["tone_family::ma"],
    }
    monkeypatch.setattr(
        maintenance,
        "notes_for_model",
        lambda model: [parent] if model == "ToneFamily" else [vocabulary],
    )
    monkeypatch.setattr(
        maintenance,
        "invoke",
        lambda action, **_kwargs: (
            ["Vietnamese", "English", "Source", "Related Words"]
            if action == "modelFieldNames"
            else None
        ),
    )

    changes, stats = maintenance.prepare_reimport(tmp_path, "Vocabulary", "Vietnamese")

    assert {change["id"] for change in changes} == {7}
    assert stats["matched"] == 1
    assert "related-words-table" in changes[0]["fields"]["Related Words"]
