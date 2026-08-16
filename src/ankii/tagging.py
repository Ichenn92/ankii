from __future__ import annotations

import json
from pathlib import Path

from ankii.keychain import get_openai_api_key
from ankii.review import (
    ALLOWED_AI_TAGS,
    has_complete_ai_taxonomy,
    load_review,
    replace_ai_tags,
    save_review,
    validate_review_profile,
)
from ankii.settings import DEFAULT_PROFILE, LanguageProfile


def suggest_example_sentence(
    word: str,
    meaning: str,
    model: str,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> tuple[str, str]:
    api_key, _source = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key was found. Run 'ankii key set' or export OPENAI_API_KEY."
        )

    try:
        from openai import OpenAI
        from pydantic import BaseModel
    except ImportError as exc:
        message = 'AI support is not installed. Run: python -m pip install -e ".[ai]"'
        raise RuntimeError(message) from exc

    class ExampleSentence(BaseModel):
        target: str
        native: str

    response = OpenAI(api_key=api_key).responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    f"You write natural, concise {profile.study_language} example sentences "
                    f"and provide faithful {profile.native_language} translations."
                ),
            },
            {
                "role": "user",
                "content": (
                    f'Write one {profile.study_language} example sentence using "{word}" with '
                    f'the intended {profile.native_language} meaning "{meaning}". Keep it '
                    "suitable for a vocabulary flashcard."
                ),
            },
        ],
        text_format=ExampleSentence,
        reasoning={"effort": "low"},
        store=False,
    )
    parsed = response.output_parsed
    target = getattr(parsed, "target", getattr(parsed, "vietnamese", "")) if parsed else ""
    native = getattr(parsed, "native", getattr(parsed, "english", "")) if parsed else ""
    if not str(target).strip() or not str(native).strip():
        raise RuntimeError("OpenAI did not return a complete bilingual example sentence.")
    return str(target).strip(), str(native).strip()


def suggest_card_tags(
    card: dict[str, object],
    model: str,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> tuple[list[str], str]:
    api_key, _source = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key was found. Run 'ankii key set' or export OPENAI_API_KEY."
        )

    try:
        from openai import OpenAI
        from pydantic import BaseModel
    except ImportError as exc:
        message = 'AI support is not installed. Run: python -m pip install -e ".[ai]"'
        raise RuntimeError(message) from exc

    class TaggedCard(BaseModel):
        tags: list[str]
        explanation: str

    prompt = (
        f"Tag this {profile.study_language} vocabulary card for a "
        f"{profile.native_language}-speaking learner. Choose exactly one part_of_speech tag, "
        "one topic tag, one register tag, and one level tag from the allowed taxonomy. "
        "Keep the explanation under 20 words.\n\n"
        f"Allowed taxonomy:\n{json.dumps(sorted(ALLOWED_AI_TAGS), ensure_ascii=False)}\n\n"
        f"Card:\n{json.dumps(card, ensure_ascii=False)}"
    )
    response = OpenAI(api_key=api_key).responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    f"You classify {profile.study_language} vocabulary using only the supplied "
                    "taxonomy."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        text_format=TaggedCard,
        reasoning={"effort": "low"},
        store=False,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI did not return structured tag data.")
    if not has_complete_ai_taxonomy(parsed.tags):
        raise RuntimeError("OpenAI returned invalid tags. No card was changed.")
    return parsed.tags, parsed.explanation.strip()


def tag_review(
    path: Path, model: str, profile: LanguageProfile = DEFAULT_PROFILE
) -> int:
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

    class TaggedCard(BaseModel):
        index: int = Field(ge=0)
        tags: list[str]
        explanation: str

    class TagBatch(BaseModel):
        cards: list[TaggedCard]

    review = load_review(path)
    validate_review_profile(review, profile)
    cards = review["cards"]
    vocabulary = [
        {
            "index": index,
            "word": card["word"],
            "meaning": card["meaning"],
            "example_vn": card.get("example_vn", ""),
            "example_en": card.get("example_en", ""),
        }
        for index, card in enumerate(cards)
    ]
    taxonomy = sorted(ALLOWED_AI_TAGS)
    prompt = (
        f"Tag each {profile.study_language} vocabulary card for a "
        f"{profile.native_language}-speaking learner. Return every input index exactly once. "
        "Choose exactly one part_of_speech tag, one topic tag, one register tag, and "
        "one level tag from the allowed taxonomy. Keep each explanation under 20 words.\n\n"
        f"Allowed taxonomy:\n{json.dumps(taxonomy, ensure_ascii=False)}\n\n"
        f"Cards:\n{json.dumps(vocabulary, ensure_ascii=False)}"
    )

    response = OpenAI(api_key=api_key).responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    f"You classify {profile.study_language} vocabulary using only the supplied "
                    "taxonomy."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        text_format=TagBatch,
        reasoning={"effort": "low"},
        store=False,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI did not return structured tag data.")
    if len(parsed.cards) != len(cards):
        message = (
            f"OpenAI returned {len(parsed.cards)} cards; expected {len(cards)}. "
            "No file was changed."
        )
        raise RuntimeError(message)

    by_index = {item.index: item for item in parsed.cards}
    if set(by_index) != set(range(len(cards))):
        message = "OpenAI returned missing or duplicate card indexes. No file was changed."
        raise RuntimeError(message)

    for index, card in enumerate(cards):
        suggestion = by_index[index]
        if not has_complete_ai_taxonomy(suggestion.tags):
            message = f"OpenAI returned invalid tags for card {index + 1}. No file was changed."
            raise RuntimeError(message)
        card["tags"] = replace_ai_tags(card["tags"], suggestion.tags)
        card["ai_explanation"] = suggestion.explanation.strip()

    review["tagging"] = {"provider": "openai", "model": model}
    save_review(review, path)
    return len(cards)
