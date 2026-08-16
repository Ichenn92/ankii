from __future__ import annotations

import json
import os
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from ankii.yourhomework import Lesson

REVIEW_VERSION = 2
SUPPORTED_REVIEW_VERSIONS = {1, 2}
LANGUAGE_ALIASES = {
    "en": "english",
    "eng": "english",
    "english": "english",
    "fr": "french",
    "fra": "french",
    "fre": "french",
    "french": "french",
    "vi": "vietnamese",
    "vie": "vietnamese",
    "vietnamese": "vietnamese",
}


def _language_key(value: str) -> str:
    normalized = value.strip().casefold().replace("_", "-")
    primary = normalized.split("-", 1)[0]
    return LANGUAGE_ALIASES.get(normalized, LANGUAGE_ALIASES.get(primary, normalized))


BASE_TAGS = ("source::yourhomework",)
AI_TAG_PREFIXES = ("part_of_speech::", "topic::", "register::", "level::")
ALLOWED_AI_TAGS = {
    "part_of_speech::noun",
    "part_of_speech::verb",
    "part_of_speech::adjective",
    "part_of_speech::adverb",
    "part_of_speech::pronoun",
    "part_of_speech::article",
    "part_of_speech::determiner",
    "part_of_speech::interjection",
    "part_of_speech::classifier",
    "part_of_speech::preposition",
    "part_of_speech::conjunction",
    "part_of_speech::particle",
    "part_of_speech::numeral",
    "part_of_speech::expression",
    "part_of_speech::other",
    "topic::animals",
    "topic::animals::mammals",
    "topic::animals::birds",
    "topic::animals::insects",
    "topic::animals::marine_animals",
    "topic::animals::reptiles_and_more",
    "topic::sports",
    "topic::geography",
    "topic::numbers",
    "topic::body",
    "topic::home",
    "topic::food",
    "topic::drink",
    "topic::restaurant",
    "topic::daily_life",
    "topic::travel",
    "topic::transport",
    "topic::culture",
    "topic::education",
    "topic::nature",
    "topic::clothing",
    "topic::science",
    "topic::city",
    "topic::health",
    "topic::business",
    "topic::objects",
    "topic::household",
    "topic::people",
    "topic::time",
    "topic::communication",
    "topic::other",
    "register::neutral",
    "register::informal",
    "register::formal",
    "register::literary",
    "register::slang",
    "register::regional",
    "register::southern",
    "register::northern",
    "level::A1",
    "level::A2",
    "level::B1",
    "level::B2",
    "level::C1",
    "level::C2",
}


def new_import_id() -> str:
    return f"ankii:{uuid.uuid4()}"


def ensure_import_ids(review: dict[str, Any]) -> int:
    added = 0
    for card in review.get("cards", []):
        if isinstance(card, dict) and not str(card.get("import_id", "")).strip():
            card["import_id"] = new_import_id()
            added += 1
    return added


def has_complete_ai_taxonomy(tags: object) -> bool:
    """Return whether tags contain exactly one allowed value for every AI dimension."""
    if not isinstance(tags, list) or len(tags) != len(AI_TAG_PREFIXES):
        return False
    if any(not isinstance(tag, str) or tag not in ALLOWED_AI_TAGS for tag in tags):
        return False
    return all(sum(tag.startswith(prefix) for tag in tags) == 1 for prefix in AI_TAG_PREFIXES)


def validate_review_profile(review: dict[str, Any], profile: object) -> None:
    """Reject an explicitly selected review that belongs to another language profile."""
    expected_name = str(profile.name)
    expected_language = str(profile.study_language)
    metadata = review.get("profile")
    if isinstance(metadata, dict) and metadata.get("name") not in (None, expected_name):
        raise ValueError(
            f"Review belongs to profile {metadata.get('name')!r}, not {expected_name!r}."
        )
    source_language = str(review.get("lesson", {}).get("source_language", "")).strip()
    source_key = _language_key(source_language)
    expected_key = _language_key(expected_language)
    if source_language and source_key != expected_key:
        raise ValueError(
            f"Review studies {source_language!r}, not active language {expected_language!r}."
        )


def create_review(lesson: Lesson, profile: object | None = None) -> dict[str, Any]:
    lesson_tag = f"lesson::{lesson.public_id}"
    result = {
        "review_version": REVIEW_VERSION,
        "lesson": {
            "public_id": lesson.public_id,
            "title": lesson.title,
            "source_language": lesson.source_language,
            "source_url": lesson.source_url,
        },
        "cards": [
            {
                **vars(item),
                "import_id": new_import_id(),
                "tags": [*BASE_TAGS, lesson_tag],
                "ai_explanation": "",
                "approved": False,
                "skip": False,
            }
            for item in lesson.items
        ],
    }
    if profile is not None:
        result["profile"] = {
            "name": str(profile.name),
            "study_language": str(profile.study_language),
            "native_language": str(profile.native_language),
        }
        for card in result["cards"]:
            tag = str(profile.language_tag)
            if tag not in card["tags"]:
                card["tags"].append(tag)
    return result


def load_review(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid review JSON in {path}: {exc}") from exc

    if not isinstance(data, dict) or data.get("review_version") not in SUPPORTED_REVIEW_VERSIONS:
        raise ValueError(f"{path} is not a supported ankii review file.")
    if not isinstance(data.get("lesson"), dict) or not isinstance(data.get("cards"), list):
        raise ValueError(f"{path} is missing lesson or cards data.")

    required = {"word", "meaning", "tags", "approved", "skip"}
    for index, card in enumerate(data["cards"], start=1):
        if not isinstance(card, dict) or not required.issubset(card):
            raise ValueError(f"Card {index} in {path} is malformed.")
        if not isinstance(card["tags"], list):
            raise ValueError(f"Card {index} in {path} has invalid tags.")
        # Version 2 uses neutral example names. Preserve aliases in memory so old
        # callers and version-1 archives remain readable during the migration.
        if "example_target" in card:
            card.setdefault("example_vn", card["example_target"])
        elif "example_vn" in card:
            card.setdefault("example_target", card["example_vn"])
        if "example_native" in card:
            card.setdefault("example_en", card["example_native"])
        elif "example_en" in card:
            card.setdefault("example_native", card["example_en"])
    return data


def save_review(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialized_review(data)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _serialized_review(data: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(data)
    payload["review_version"] = REVIEW_VERSION
    for card in payload.get("cards", []):
        if not isinstance(card, dict):
            continue
        if "example_target" not in card and "example_vn" in card:
            card["example_target"] = card["example_vn"]
        if "example_native" not in card and "example_en" in card:
            card["example_native"] = card["example_en"]
        card.pop("example_vn", None)
        card.pop("example_en", None)
    return payload


def save_review_atomic(data: dict[str, Any], path: Path) -> None:
    """Write a review without exposing a partially written JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(_serialized_review(data), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def replace_ai_tags(existing: list[str], suggested: list[str]) -> list[str]:
    preserved = [tag for tag in existing if not tag.startswith(AI_TAG_PREFIXES)]
    valid = [tag for tag in suggested if tag in ALLOWED_AI_TAGS]
    return list(dict.fromkeys([*preserved, *valid]))
