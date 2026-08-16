from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path
from typing import Any

from ankii.anki import invoke
from ankii.maintenance import review_files
from ankii.review import load_review, new_import_id, save_review_atomic


def _value(note: dict[str, Any], field: str) -> str:
    return html.unescape(str(note.get("fields", {}).get(field, {}).get("value", ""))).strip()


def _card_model(card: dict[str, Any]) -> str:
    if card.get("card_type") == "grammar" or "card_type::grammar" in card.get("tags", []):
        return "Grammar"
    return "Vocabulary"


def _source(card: dict[str, Any], lesson: dict[str, Any]) -> str:
    parts = [str(card.get("source_title", "")).strip(), str(card.get("source_url", "")).strip()]
    source = " — ".join(part for part in parts if part)
    return source or str(lesson.get("source_url", "")).strip()


def backfill_import_ids(root: Path, *, apply: bool = False) -> dict[str, int]:
    models = {
        "Vocabulary": ("Vietnamese", invoke("findNotes", query='note:"Vocabulary"')),
        "Grammar": ("Grammar", invoke("findNotes", query='note:"Grammar"')),
    }
    notes_by_model: dict[str, list[dict[str, Any]]] = {}
    notes_by_id: dict[int, dict[str, Any]] = {}
    by_word: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for model, (word_field, note_ids) in models.items():
        notes = invoke("notesInfo", notes=note_ids) if note_ids else []
        notes_by_model[model] = notes
        words: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for note in notes:
            notes_by_id[int(note["noteId"])] = note
            words[_value(note, word_field).casefold()].append(note)
        by_word[model] = words

    note_assignments: dict[int, str] = {}
    changed_reviews: dict[Path, dict[str, Any]] = {}
    stats = {
        "files": 0,
        "cards": 0,
        "review_ids_added": 0,
        "notes_matched": 0,
        "notes_updated": 0,
        "unmatched": 0,
        "ambiguous": 0,
    }
    for path in review_files(root):
        try:
            review = load_review(path)
        except (OSError, ValueError):
            continue
        stats["files"] += 1
        changed = False
        lesson = review.get("lesson", {})
        for card in review["cards"]:
            stats["cards"] += 1
            model = _card_model(card)
            candidates: list[dict[str, Any]] = []
            imported_id = card.get("import", {}).get("anki_note_id")
            if isinstance(imported_id, int) and imported_id in notes_by_id:
                candidate = notes_by_id[imported_id]
                word_field = models[model][0]
                if _value(candidate, word_field):
                    candidates = [candidate]
            if not candidates:
                candidates = list(by_word[model][str(card.get("word", "")).strip().casefold()])
            if len(candidates) > 1:
                expected_source = _source(card, lesson)
                source_matches = [
                    note for note in candidates if _value(note, "Source") == expected_source
                ]
                if source_matches:
                    candidates = source_matches

            import_id = str(card.get("import_id", "")).strip()
            if len(candidates) == 1:
                note = candidates[0]
                note_id = int(note["noteId"])
                existing = _value(note, "Import ID") or note_assignments.get(note_id, "")
                import_id = import_id or existing or new_import_id()
                if existing and import_id != existing:
                    raise ValueError(f"Conflicting Import IDs for Anki note {note_id}.")
                note_assignments[note_id] = import_id
                stats["notes_matched"] += 1
            elif len(candidates) > 1:
                stats["ambiguous"] += 1
                import_id = import_id or new_import_id()
            else:
                stats["unmatched"] += 1
                import_id = import_id or new_import_id()
            if card.get("import_id") != import_id:
                card["import_id"] = import_id
                stats["review_ids_added"] += 1
                changed = True
        if changed:
            changed_reviews[path] = review

    for note_id, import_id in note_assignments.items():
        if _value(notes_by_id[note_id], "Import ID") != import_id:
            stats["notes_updated"] += 1

    if apply:
        for path, review in changed_reviews.items():
            save_review_atomic(review, path)
        for note_id, import_id in note_assignments.items():
            if _value(notes_by_id[note_id], "Import ID") != import_id:
                invoke(
                    "updateNoteFields",
                    note={"id": note_id, "fields": {"Import ID": import_id}},
                )
    return stats
