import json
from pathlib import Path

import pytest

from ankii import cli
from ankii.settings import LanguageProfile

FRENCH = LanguageProfile("french", "French", "English", "French", "A1", "B2")


def _review(path: Path, *, approved: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "review_version": 2,
                "profile": {
                    "name": "french",
                    "study_language": "French",
                    "native_language": "English",
                },
                "lesson": {"source_language": "fr"},
                "cards": [
                    {
                        "word": "bonjour",
                        "meaning": "hello",
                        "tags": [],
                        "approved": approved,
                        "skip": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_approve_review_file_is_optional() -> None:
    args = cli.build_parser().parse_args(["approve"])

    assert args.review_file is None


def test_approve_prompts_only_for_pending_profile_reviews(monkeypatch, tmp_path: Path) -> None:
    profile = LanguageProfile("french", "French", "English", "French", "A1", "B2")
    monkeypatch.chdir(tmp_path)
    pending = Path("reviews/french/pending.review.json")
    _review(pending, approved=False)
    _review(Path("reviews/french/done.review.json"), approved=True)
    _review(Path("reviews/french/archive/old.review.json"), approved=False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")

    assert cli._resolve_approve_file(None, profile) == pending


def test_approve_reports_when_nothing_is_pending(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _review(Path("reviews/french/done.review.json"), approved=True)

    with pytest.raises(ValueError, match="No reviews with pending cards"):
        cli._resolve_approve_file(None, FRENCH)
