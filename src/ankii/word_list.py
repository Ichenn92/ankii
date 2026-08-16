from __future__ import annotations

import json
from typing import Any

from ankii.keychain import get_openai_api_key
from ankii.review import ALLOWED_AI_TAGS, REVIEW_VERSION, has_complete_ai_taxonomy, new_import_id
from ankii.settings import DEFAULT_PROFILE, LanguageProfile


def generate_word_list_review(
    entries: list[str],
    title: str,
    model: str,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> dict[str, Any]:
    """Turn target-language, native-language, or paired entries into a review."""
    if not entries:
        raise ValueError("The word list is empty.")

    api_key, _source = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key was found. Run 'ankii key set' or export OPENAI_API_KEY."
        )

    try:
        from openai import OpenAI
        from pydantic import BaseModel, Field
    except ImportError as exc:
        message = 'AI support is not installed. Run: python -m pip install -e ".[ai]"'
        raise RuntimeError(message) from exc

    class GeneratedCard(BaseModel):
        index: int = Field(ge=0)
        word: str
        meaning: str
        example_target: str
        example_native: str
        tags: list[str]
        explanation: str

    class GeneratedBatch(BaseModel):
        cards: list[GeneratedCard]

    allowed_taxonomy = {
        tag
        for tag in ALLOWED_AI_TAGS
        if not tag.startswith("level::")
        or tag.removeprefix("level::") in profile.analysis_levels
    }
    indexed_entries = [{"index": index, "entry": entry} for index, entry in enumerate(entries)]
    prompt = (
        f"Create one vocabulary flashcard for every input entry for a learner of "
        f"{profile.study_language} whose native language is {profile.native_language}. "
        f"An entry may be in {profile.study_language}, in {profile.native_language}, or contain "
        "both sides as a pair. Infer which information was supplied. Set word to the natural "
        f"{profile.study_language} headword and meaning to a concise {profile.native_language} "
        "translation. Preserve the intended sense of paired entries. Write one short, natural "
        f"{profile.study_language} example sentence and a faithful {profile.native_language} "
        "translation. Choose exactly one allowed tag from each taxonomy dimension: "
        "part_of_speech, topic, register, and level. Keep explanation under 20 words. Return "
        "every input index exactly once and do not combine or omit entries.\n\n"
        f"Allowed taxonomy:\n{json.dumps(sorted(allowed_taxonomy), ensure_ascii=False)}\n\n"
        f"Entries:\n{json.dumps(indexed_entries, ensure_ascii=False)}"
    )
    response = OpenAI(api_key=api_key).responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    f"You are a precise bilingual {profile.study_language} and "
                    f"{profile.native_language} vocabulary editor."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        text_format=GeneratedBatch,
        reasoning={"effort": "low"},
        store=False,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI did not return structured vocabulary cards.")
    if len(parsed.cards) != len(entries):
        raise RuntimeError(
            f"OpenAI returned {len(parsed.cards)} cards; expected {len(entries)}. "
            "No file was created."
        )
    by_index = {card.index: card for card in parsed.cards}
    if len(by_index) != len(parsed.cards) or set(by_index) != set(range(len(entries))):
        raise RuntimeError(
            "OpenAI returned missing or duplicate input indexes. No file was created."
        )

    cards: list[dict[str, Any]] = []
    for index in range(len(entries)):
        generated = by_index[index]
        values = (
            generated.word,
            generated.meaning,
            generated.example_target,
            generated.example_native,
        )
        if any(not value.strip() for value in values):
            raise RuntimeError(
                f"OpenAI returned incomplete data for entry {index + 1}. No file was created."
            )
        if not has_complete_ai_taxonomy(generated.tags):
            raise RuntimeError(
                f"OpenAI returned invalid tags for entry {index + 1}. No file was created."
            )
        level = next(
            tag.removeprefix("level::")
            for tag in generated.tags
            if tag.startswith("level::")
        )
        if level not in profile.analysis_levels:
            raise RuntimeError(
                f"OpenAI returned an out-of-range level for entry {index + 1}. "
                "No file was created."
            )
        cards.append(
            {
                "word": generated.word.strip(),
                "meaning": generated.meaning.strip(),
                "example_target": generated.example_target.strip(),
                "example_native": generated.example_native.strip(),
                "image_url": "",
                "image_source_url": "",
                "image_attribution": "",
                "image_license_url": "",
                "import_id": new_import_id(),
                "tags": [
                    "source::word-list",
                    "card_type::vocabulary",
                    profile.language_tag,
                    *generated.tags,
                ],
                "ai_explanation": generated.explanation.strip(),
                "approved": False,
                "skip": False,
            }
        )

    return {
        "review_version": REVIEW_VERSION,
        "review_kind": "generated_word_list",
        "profile": {
            "name": profile.name,
            "study_language": profile.study_language,
            "native_language": profile.native_language,
        },
        "lesson": {
            "public_id": "word-list",
            "title": title,
            "source_language": profile.study_language,
            "source_url": "",
        },
        "generation": {"provider": "openai", "model": model},
        "cards": cards,
    }
