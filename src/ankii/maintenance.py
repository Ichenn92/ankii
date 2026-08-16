from __future__ import annotations

import html
from collections import defaultdict
from pathlib import Path
from typing import Any

from ankii.anki import invoke
from ankii.importer import build_note, infer_field_names
from ankii.review import replace_ai_tags
from ankii.settings import DEFAULT_PROFILE, LanguageProfile
from ankii.tagging import suggest_card_tags


def _query_value(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notes_for_model(model: str, deck: str | None = None) -> list[dict[str, Any]]:
    query = f"note:{_query_value(model)}"
    if deck:
        query += f" deck:{_query_value(deck)}"
    note_ids = invoke("findNotes", query=query)
    if not isinstance(note_ids, list):
        raise RuntimeError("AnkiConnect returned invalid note IDs.")
    if not note_ids:
        return []
    notes = invoke("notesInfo", notes=note_ids)
    if not isinstance(notes, list):
        raise RuntimeError("AnkiConnect returned invalid note details.")
    return notes


def _field_value(note: dict[str, Any], field: str) -> str:
    value = note.get("fields", {}).get(field, {})
    return html.unescape(str(value.get("value", ""))).strip() if isinstance(value, dict) else ""


def retag_notes(
    model: str,
    ai_model: str,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> list[dict[str, Any]]:
    fields = invoke("modelFieldNames", modelName=model)
    field_names = infer_field_names(fields)
    changes: list[dict[str, Any]] = []
    notes = (
        notes_for_model(model)
        if profile == DEFAULT_PROFILE
        else notes_for_model(model, profile.deck)
    )
    for note in notes:
        card = {
            "word": _field_value(note, field_names["target"]),
            "meaning": _field_value(note, field_names["native"]),
            "example_target": _field_value(note, field_names["example_target"]),
            "example_native": _field_value(note, field_names["example_native"]),
        }
        if profile == DEFAULT_PROFILE:
            legacy_card = {
                **card,
                "example_vn": card["example_target"],
                "example_en": card["example_native"],
            }
            tags, explanation = suggest_card_tags(legacy_card, ai_model)
        else:
            tags, explanation = suggest_card_tags(card, ai_model, profile)
        old_tags = [str(tag) for tag in note.get("tags", [])]
        new_tags = replace_ai_tags(old_tags, tags)
        changes.append(
            {
                "id": note["noteId"],
                "word": card["word"],
                "old_tags": old_tags,
                "new_tags": new_tags,
                "explanation": explanation,
            }
        )
    return changes


def apply_retags(changes: list[dict[str, Any]]) -> int:
    changed = 0
    for change in changes:
        if change["old_tags"] == change["new_tags"]:
            continue
        invoke("updateNote", note={"id": change["id"], "tags": change["new_tags"]})
        changed += 1
    return changed


def review_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.json"), key=lambda path: str(path).casefold())


def prepare_reimport(
    root: Path, model: str, deck: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    available_fields = invoke("modelFieldNames", modelName=model)
    field_names = infer_field_names(available_fields)
    word_field = field_names["target"]
    source_field = field_names["source"]
    import_id_field = field_names["import_id"]
    by_word: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_import_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # The deck-scoped implementation is used in production. Calling through
    # one argument remains compatible with older injected test doubles.
    try:
        scoped_notes = notes_for_model(model, deck)
    except TypeError:
        scoped_notes = notes_for_model(model)
    for note in scoped_notes:
        by_word[_field_value(note, word_field).casefold()].append(note)
        import_id = _field_value(note, import_id_field)
        if import_id:
            by_import_id[import_id].append(note)

    from ankii.review import load_review

    changes: list[dict[str, Any]] = []
    stats = {"files": 0, "cards": 0, "matched": 0, "missing": 0, "ambiguous": 0}
    change_by_id: dict[int, dict[str, Any]] = {}
    conflicted: set[int] = set()
    for path in review_files(root):
        try:
            review = load_review(path)
        except (OSError, ValueError):
            continue
        stats["files"] += 1
        family = None
        if review.get("review_kind") == "tone_family":
            from ankii.tone_family import tone_family_from_review

            family = tone_family_from_review(review)
        for card in review["cards"]:
            if card.get("skip"):
                continue
            stats["cards"] += 1
            import_id = str(card.get("import_id", "")).strip()
            candidates = by_import_id[import_id] if import_id else []
            if not candidates:
                candidates = by_word[str(card["word"]).strip().casefold()]
            source = str(review["lesson"].get("source_url", "")).strip()
            if source and len(candidates) > 1:
                source_matches = [
                    note for note in candidates if _field_value(note, source_field) == source
                ]
                if source_matches:
                    candidates = source_matches
            if not candidates:
                stats["missing"] += 1
                continue
            if len(candidates) != 1:
                stats["ambiguous"] += 1
                continue
            note = candidates[0]
            note_id = int(note["noteId"])
            if note_id in conflicted:
                stats["ambiguous"] += 1
                continue
            if note_id in change_by_id:
                change_by_id.pop(note_id)
                stats["matched"] -= 1
                stats["ambiguous"] += 2
                conflicted.add(note_id)
                continue
            if family is not None:
                from ankii.tone_family import build_tone_vocabulary_note

                entry = next(item for item in family.entries if item.form == card["word"])
                desired = build_tone_vocabulary_note(
                    entry, family, deck, model, set(available_fields)
                )
            else:
                desired = build_note(
                    card, review["lesson"], deck, model, set(available_fields), field_names
                )
            change_by_id[note_id] = {
                "id": note_id,
                "word": card["word"],
                "fields": desired["fields"],
                "tags": desired["tags"],
                "picture": desired.get("picture"),
            }
            stats["matched"] += 1
    changes.extend(change_by_id.values())
    return changes, stats


def apply_reimport(changes: list[dict[str, Any]]) -> int:
    for change in changes:
        note: dict[str, Any] = {
            "id": change["id"],
            "fields": change["fields"],
            "tags": change["tags"],
        }
        if change["picture"]:
            note["picture"] = [change["picture"]]
        invoke("updateNote", request_timeout=180, note=note)
    return len(changes)
