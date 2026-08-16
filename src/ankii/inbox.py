from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ankii.review import (
    REVIEW_VERSION,
    ensure_import_ids,
    load_review,
    save_review_atomic,
    validate_review_profile,
)
from ankii.settings import DEFAULT_PROFILE, LanguageProfile

INBOX_KIND = "manual_inbox"


def empty_inbox(profile: LanguageProfile = DEFAULT_PROFILE) -> dict[str, Any]:
    return {
        "review_version": REVIEW_VERSION,
        "review_kind": INBOX_KIND,
        "lesson": {
            "public_id": "manual-inbox",
            "title": "Manual vocabulary",
            "source_language": profile.study_language,
            "source_url": "",
        },
        "profile": {
            "name": profile.name,
            "study_language": profile.study_language,
            "native_language": profile.native_language,
        },
        "cards": [],
    }


def load_or_create_inbox(
    path: Path, profile: LanguageProfile = DEFAULT_PROFILE
) -> dict[str, Any]:
    if not path.exists():
        return empty_inbox(profile)
    review = load_review(path)
    if review.get("review_kind") != INBOX_KIND:
        raise ValueError(f"{path} is not a manual vocabulary inbox.")
    validate_review_profile(review, profile)
    return review


def append_card(
    path: Path, card: dict[str, Any], profile: LanguageProfile = DEFAULT_PROFILE
) -> int:
    inbox = load_or_create_inbox(path, profile)
    inbox["cards"].append(card)
    ensure_import_ids(inbox)
    save_review_atomic(inbox, path)
    return len(inbox["cards"])


def append_cards(
    path: Path, cards: list[dict[str, Any]], profile: LanguageProfile = DEFAULT_PROFILE
) -> int:
    """Append a batch atomically and return the new inbox size."""
    inbox = load_or_create_inbox(path, profile)
    inbox["cards"].extend(cards)
    ensure_import_ids(inbox)
    save_review_atomic(inbox, path)
    return len(inbox["cards"])


def _archive_path(review_path: Path, imported_at: datetime) -> Path:
    archive_dir = review_path.parent / "archive"
    timestamp = imported_at.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    base = archive_dir / f"inbox-{timestamp}.imported.json"
    if not base.exists():
        return base
    counter = 2
    while True:
        candidate = archive_dir / f"inbox-{timestamp}-{counter}.imported.json"
        if not candidate.exists():
            return candidate
        counter += 1


def archive_completed_review(review_path: Path) -> Path | None:
    """Move a completed non-inbox review into its sibling archive directory."""
    review = load_review(review_path) if review_path.exists() else None
    if review is None or review.get("review_kind") == INBOX_KIND:
        return None

    archive_dir = review_path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / review_path.name
    if archive_path.exists():
        counter = 2
        while True:
            candidate = archive_dir / f"{review_path.stem}-{counter}{review_path.suffix}"
            if not candidate.exists():
                archive_path = candidate
                break
            counter += 1
    review_path.replace(archive_path)
    return archive_path


def archive_imported_cards(
    review_path: Path,
    review: dict[str, Any],
    imported: list[tuple[int, int]],
    deck: str,
    model: str,
    *,
    imported_at: datetime | None = None,
) -> Path | None:
    """Archive successful inbox cards, then atomically remove them from the inbox."""
    if review.get("review_kind") != INBOX_KIND or not imported:
        return None

    imported_at = imported_at or datetime.now(UTC)
    imported_by_index = dict(imported)
    timestamp = imported_at.astimezone(UTC).isoformat()
    archived_cards: list[dict[str, Any]] = []
    remaining_cards: list[dict[str, Any]] = []
    for index, card in enumerate(review["cards"]):
        if index not in imported_by_index:
            remaining_cards.append(card)
            continue
        archived = deepcopy(card)
        archived["import"] = {
            "imported_at": timestamp,
            "anki_note_id": imported_by_index[index],
            "deck": deck,
            "model": model,
        }
        archived_cards.append(archived)

    archive = deepcopy(review)
    archive["review_kind"] = "manual_inbox_archive"
    archive["cards"] = archived_cards
    archive_path = _archive_path(review_path, imported_at)
    save_review_atomic(archive, archive_path)

    active = deepcopy(review)
    active["cards"] = remaining_cards
    save_review_atomic(active, review_path)
    return archive_path
