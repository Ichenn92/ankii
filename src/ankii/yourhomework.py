from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

BASE_URL = "https://yourhomework.net"
PUBLIC_ID_PATTERN = re.compile(r"^\d+$")


@dataclass
class VocabularyItem:
    word: str
    meaning: str
    example_vn: str
    example_en: str
    image_url: str


@dataclass
class Lesson:
    public_id: str
    title: str
    source_language: str
    source_url: str
    items: list[VocabularyItem]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_public_id(value: str) -> str:
    value = value.strip().rstrip("/")
    candidate = value.split("/")[-1]

    if not PUBLIC_ID_PATTERN.fullmatch(candidate):
        raise ValueError(
            "Expected a numeric lesson ID or a URL such as "
            "https://yourhomework.net/vocab/313789981"
        )

    return candidate


def make_absolute_url(value: str) -> str:
    if not value:
        return ""

    if value.startswith(("https://", "http://")):
        return value

    if value.startswith("/"):
        return f"{BASE_URL}{value}"

    return f"{BASE_URL}/{value.lstrip('/')}"


def fetch_lesson(value: str) -> Lesson:
    public_id = extract_public_id(value)
    api_url = f"{BASE_URL}/api/v1/vocab/{public_id}/activity-data"
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ankii/0.1",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"YourHomework returned HTTP {exc.code} for lesson {public_id}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not contact YourHomework: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("YourHomework returned an invalid JSON response.") from exc

    if not isinstance(payload, dict):
        raise TypeError("The YourHomework response was not a JSON object.")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise TypeError("The YourHomework response did not contain an items list.")

    items = [
        VocabularyItem(
            word=str(item.get("word", "")).strip(),
            meaning=str(item.get("meaning", "")).strip(),
            example_vn=str(item.get("exampleText", "")).strip(),
            example_en=str(item.get("exampleMeaning", "")).strip(),
            image_url=make_absolute_url(str(item.get("imageUrl", "")).strip()),
        )
        for item in raw_items
        if isinstance(item, dict)
    ]

    return Lesson(
        public_id=public_id,
        title=str(payload.get("vocabTitle", f"Lesson {public_id}")).strip(),
        source_language=str(payload.get("sourceLangValue", "")).strip(),
        source_url=f"{BASE_URL}/vocab/{public_id}",
        items=[item for item in items if item.word],
    )
