from __future__ import annotations

import hashlib
import html
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ankii.anki import invoke
from ankii.review import ensure_import_ids, load_review, save_review_atomic

GENERIC_FIELD_DEFAULTS = {
    "target": "Target",
    "native": "Native",
    "example_target": "Example Target",
    "example_native": "Example Native",
    "source": "Source",
    "lesson": "Lesson",
    "explanation": "AIExplanation",
    "image": "Image",
    "import_id": "Import ID",
}

# Public compatibility mapping for version-1 callers. New commands use
# GENERIC_FIELD_DEFAULTS and inference always prefers the generic schema.
FIELD_DEFAULTS = {
    "vietnamese": "Vietnamese",
    "english": "English",
    "example_vn": "Example VN",
    "example_en": "Example EN",
    "source": "Source",
    "lesson": "Lesson",
    "explanation": "AIExplanation",
    "image": "Image",
    "import_id": "Import ID",
}

FIELD_ALIASES = {
    "target": ("Target", "Vietnamese", "Front", "Word", "Expression"),
    "native": ("Native", "English", "Back", "Meaning", "Definition"),
    "example_target": ("Example Target", "Example VN", "ExampleVN", "Example", "Examples"),
    "example_native": ("Example Native", "Example EN", "ExampleEN", "Example Translation"),
    "source": ("Source", "URL"),
    "lesson": ("Lesson", "Unit"),
    "explanation": ("AIExplanation", "Notes", "Note"),
    "image": ("Image", "Visual Media", "Picture"),
    "import_id": ("Import ID", "ImportID"),
}

GENERIC_GRAMMAR_FIELDS = {
    "grammar": "Grammar",
    "explanation": "Explanation",
    "example_target": "Example Target",
    "example_native": "Example Native",
    "source": "Source",
    "ai_explanation": "AIExplanation",
    "import_id": "Import ID",
}
GRAMMAR_FIELDS = {
    "grammar": "Grammar",
    "explanation": "Explanation",
    "example_vn": "Example VN",
    "example_en": "Example EN",
    "source": "Source",
    "ai_explanation": "AIExplanation",
    "import_id": "Import ID",
}


def _format_field(key: str, value: object) -> str:
    escaped = html.escape(str(value))
    if key in {"example_target", "example_native"}:
        return escaped.replace("\n", "<br>")
    return escaped


def infer_field_names(available_fields: list[str]) -> dict[str, str]:
    available = set(available_fields)
    result: dict[str, str] = {}
    for key, aliases in FIELD_ALIASES.items():
        result[key] = next(
            (name for name in aliases if name in available), GENERIC_FIELD_DEFAULTS[key]
        )
    result.update(
        {
            "vietnamese": result["target"],
            "english": result["native"],
            "example_vn": result["example_target"],
            "example_en": result["example_native"],
        }
    )
    return result


def _image_filename(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if not suffix or len(suffix) > 8:
        suffix = ".jpg"
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"ankii-{digest}{suffix}"


def build_note(
    card: dict[str, Any],
    lesson: dict[str, Any],
    deck: str,
    model: str,
    available_fields: set[str],
    field_names: dict[str, str],
) -> dict[str, Any]:
    field_names = dict(field_names)
    compatibility = {
        "target": "vietnamese",
        "native": "english",
        "example_target": "example_vn",
        "example_native": "example_en",
    }
    for current, legacy in compatibility.items():
        if current not in field_names and legacy in field_names:
            field_names[current] = field_names[legacy]
    for key in ("target", "native"):
        if field_names[key] not in available_fields:
            raise ValueError(f"Note type {model!r} has no field named {field_names[key]!r}.")

    source = lesson.get("source_url", "")
    if card.get("source_title") or card.get("source_url"):
        source_parts = [
            str(card.get("source_title", "")).strip(),
            str(card.get("source_url", "")).strip(),
        ]
        source = " — ".join(part for part in source_parts if part)
    if lesson.get("public_id") == "manual-inbox" and card.get("image_source_url"):
        source_parts = [
            str(card.get("image_attribution", "")).strip(),
            str(card.get("image_source_url", "")).strip(),
        ]
        source = " — ".join(part for part in source_parts if part)

    values = {
        "target": card["word"],
        "native": card["meaning"],
        "example_target": card.get("example_target", card.get("example_vn", "")),
        "example_native": card.get("example_native", card.get("example_en", "")),
        "source": source,
        "lesson": lesson.get("title", ""),
        "explanation": card.get("ai_explanation", ""),
        "image": "",
        "import_id": card.get("import_id", ""),
    }
    fields = {
        field_names[key]: _format_field(key, value)
        for key, value in values.items()
        if field_names[key] in available_fields
    }
    note: dict[str, Any] = {
        "deckName": deck,
        "modelName": model,
        "fields": fields,
        "tags": card["tags"],
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }

    image_url = card.get("image_url", "")
    image_field = field_names["image"]
    if image_url and image_field in available_fields:
        note["picture"] = {
            "url": image_url,
            "filename": _image_filename(image_url),
            "fields": [image_field],
        }
    return note


CARD_TYPES = {"vocabulary", "grammar"}


def detect_card_type(card: dict[str, Any]) -> str:
    """Return the card type encoded in a review card.

    Newer review JSON may store ``card_type`` directly, while existing files store
    it as a ``card_type::<type>`` tag. A type is mandatory for import.
    """
    explicit = card.get("card_type")
    if explicit is not None and (
        not isinstance(explicit, str) or explicit not in CARD_TYPES
    ):
        raise ValueError(
            f"Card {card.get('word', '<unknown>')!r} has unknown card_type {explicit!r}."
        )

    tagged_types = {
        tag.removeprefix("card_type::")
        for tag in card.get("tags", [])
        if isinstance(tag, str) and tag.startswith("card_type::")
    }
    unknown = tagged_types - CARD_TYPES
    if unknown:
        raise ValueError(
            f"Card {card.get('word', '<unknown>')!r} has unknown card type tag(s): "
            f"{', '.join(sorted(unknown))}."
        )
    detected = ({explicit} if explicit is not None else set()) | tagged_types
    if len(detected) > 1:
        raise ValueError(
            f"Card {card.get('word', '<unknown>')!r} has conflicting card types: "
            f"{', '.join(sorted(detected))}."
        )
    if not detected:
        raise ValueError(
            f"Card {card.get('word', '<unknown>')!r} is missing card_type. "
            "Use 'vocabulary' or 'grammar'."
        )
    return next(iter(detected))


def is_grammar_card(card: dict[str, Any]) -> bool:
    return detect_card_type(card) == "grammar"


def build_grammar_note(
    card: dict[str, Any], lesson: dict[str, Any], deck: str, model: str
) -> dict[str, Any]:
    available_fields = set(invoke("modelFieldNames", modelName=model))
    grammar_fields = (
        GENERIC_GRAMMAR_FIELDS
        if set(GENERIC_GRAMMAR_FIELDS.values()) <= available_fields
        else GRAMMAR_FIELDS
    )
    missing = set(grammar_fields.values()) - available_fields
    if missing:
        raise ValueError(
            f"Grammar note type {model!r} is missing fields: {', '.join(sorted(missing))}. "
            "Run 'ankii anki setup-note-types' first."
        )
    source_parts = [
        str(card.get("source_title", "")).strip(),
        str(card.get("source_url", "")).strip(),
    ]
    source = " — ".join(part for part in source_parts if part)
    if not source:
        source = str(lesson.get("source_url", "")).strip()
    values = {
        grammar_fields["grammar"]: card["word"],
        grammar_fields["explanation"]: card["meaning"],
        grammar_fields.get("example_target", grammar_fields.get("example_vn", "")): card.get(
            "example_target", card.get("example_vn", "")
        ),
        grammar_fields.get("example_native", grammar_fields.get("example_en", "")): card.get(
            "example_native", card.get("example_en", "")
        ),
        grammar_fields["source"]: source,
        grammar_fields["ai_explanation"]: card.get("ai_explanation", ""),
        grammar_fields["import_id"]: card.get("import_id", ""),
    }
    return {
        "deckName": deck,
        "modelName": model,
        "fields": {
            name: (
                html.escape(str(value)).replace("\n", "<br>")
                if name in {"Example Target", "Example Native", "Example VN", "Example EN"}
                else html.escape(str(value))
            )
            for name, value in values.items()
        },
        "tags": card["tags"],
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }


def prepare_import(
    review_path: Path,
    deck: str,
    model: str,
    field_names: dict[str, str],
    grammar_model: str = "Grammar",
) -> tuple[dict[str, Any], list[dict[str, Any]], list[bool]]:
    review = load_review(review_path)
    changed = ensure_import_ids(review)
    # Manual and YourHomework cards created before card-type routing were
    # unambiguously vocabulary. Analysis cards must continue to declare their
    # type because they may contain either vocabulary or grammar.
    for card in review["cards"]:
        tags = card["tags"]
        legacy_vocabulary = "source::yourhomework" in tags or (
            review.get("review_kind") == "manual_inbox" and "source::manual" in tags
        )
        if (
            legacy_vocabulary
            and not any(
                isinstance(tag, str) and tag.startswith("card_type::") for tag in tags
            )
            and "card_type" not in card
        ):
            tags.insert(1, "card_type::vocabulary")
            changed += 1
    if changed:
        save_review_atomic(review, review_path)
    approved = [card for card in review["cards"] if card["approved"] and not card["skip"]]
    if not approved:
        raise ValueError("The review contains no approved, unskipped cards.")

    decks = invoke("deckNames")
    if deck not in decks:
        raise ValueError(f"Anki deck {deck!r} does not exist.")
    models = invoke("modelNames")
    if model not in models:
        raise ValueError(f"Anki note type {model!r} does not exist.")
    available_fields = set(invoke("modelFieldNames", modelName=model))
    has_grammar = any(is_grammar_card(card) for card in approved)
    if has_grammar and grammar_model not in models:
        raise ValueError(
            f"Anki grammar note type {grammar_model!r} does not exist. "
            "Run 'ankii anki setup-note-types' first."
        )
    notes = []
    for card in approved:
        if is_grammar_card(card):
            notes.append(build_grammar_note(card, review["lesson"], deck, grammar_model))
        else:
            notes.append(
                build_note(card, review["lesson"], deck, model, available_fields, field_names)
            )
    # AnkiConnect's canAddNotes calls its full note builder, including remote media
    # downloads. Media does not affect duplicate detection, so omit it from this
    # read-only check and reserve downloads for the confirmed addNotes call.
    check_notes = [
        {key: value for key, value in note.items() if key not in {"audio", "picture", "video"}}
        for note in notes
    ]
    can_add = invoke("canAddNotes", notes=check_notes)
    if not isinstance(can_add, list) or len(can_add) != len(notes):
        raise RuntimeError("AnkiConnect returned an invalid duplicate-check response.")
    return review, notes, [bool(value) for value in can_add]


def add_notes(notes: list[dict[str, Any]]) -> list[int | None]:
    result = invoke("addNotes", request_timeout=180, notes=notes)
    if not isinstance(result, list) or len(result) != len(notes):
        raise RuntimeError("AnkiConnect returned an invalid import response.")
    return result
