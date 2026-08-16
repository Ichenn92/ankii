from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Literal

from ankii.anki import invoke
from ankii.importer import infer_field_names
from ankii.keychain import get_openai_api_key
from ankii.review import ALLOWED_AI_TAGS, has_complete_ai_taxonomy
from ankii.settings import DEFAULT_PROFILE, LanguageProfile


@dataclass(frozen=True)
class AnalysisCandidate:
    word: str
    meaning: str
    example_vn: str
    example_en: str
    rationale: str
    tags: list[str]
    card_type: Literal["vocabulary", "grammar"] = "vocabulary"
    everyday_example_vn: str = ""
    everyday_example_en: str = ""
    simple_example_vn: str = ""
    simple_example_en: str = ""


@dataclass(frozen=True)
class PassageAnalysis:
    translation: str
    interpretation: str
    styles: list[str]
    style_explanation: str
    grammar: list[tuple[str, str]]
    candidates: list[AnalysisCandidate]


def normalize_headword(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).casefold().strip()
    return re.sub(r"\s+", " ", normalized)


def analyze_passage(
    text: str,
    model: str,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> PassageAnalysis:
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

    class GrammarPoint(BaseModel):
        pattern: str
        explanation: str

    class Candidate(BaseModel):
        card_type: Literal["vocabulary", "grammar"]
        word: str
        meaning: str
        example_vn: str
        example_en: str
        rationale: str
        tags: list[str]
        everyday_example_vn: str
        everyday_example_en: str
        simple_example_vn: str
        simple_example_en: str

    class Analysis(BaseModel):
        translation: str
        interpretation: str
        styles: list[str]
        style_explanation: str
        grammar: list[GrammarPoint]
        candidates: list[Candidate] = Field(max_length=12)

    allowed_styles = [
        "standard speech",
        "informal",
        "formal",
        "regional",
        "literary",
        "poetic",
        "archaic",
        "slang",
    ]
    allowed_taxonomy = {
        tag
        for tag in ALLOWED_AI_TAGS
        if not tag.startswith("level::")
        or tag.removeprefix("level::") in profile.analysis_levels
    }
    prompt = (
        f"Analyze this {profile.study_language} passage for a "
        f"{profile.native_language}-speaking learner. Give a natural full "
        "translation, concise interpretation, important grammar, and an intentionally selective "
        "ranked list (at most 12) of learning cards. Use card_type=vocabulary for reusable words "
        "and expressions. Also propose card_type=grammar for reusable constructions found in the "
        "passage, such as conditional frames, classifier patterns, particles, or word order. For a "
        "grammar card, word is the concise pattern (for example 'có … thì …'), meaning is a clear "
        f"{profile.native_language} explanation of how it works in this passage, and rationale "
        "explains why it is "
        "worth learning; use part_of_speech::other for its taxonomy. Candidate example_vn "
        "must be an exact complete sentence from the supplied passage; example_en must translate "
        "that sentence. For every candidate, also write everyday_example_vn and "
        f"everyday_example_en: an additional natural, non-poetic "
        f"{profile.analysis_max_level}-level example in an ordinary "
        "day-to-day context that clearly demonstrates the same word or grammar pattern. Do not "
        "copy the source sentence into the everyday example. Also write simple_example_vn and "
        f"simple_example_en: a third, short, natural {profile.analysis_min_level}-level everyday "
        "example demonstrating the "
        "same item with basic vocabulary. It must differ from both other examples. Do not invent "
        "source text. Choose "
        "exactly one allowed taxonomy tag from "
        "each of the four dimensions for every candidate. Return styles only from the allowed "
        "list.\n\n"
        f"Allowed styles:\n{json.dumps(allowed_styles)}\n\n"
        f"Only propose learning cards from CEFR {profile.analysis_min_level} through "
        f"{profile.analysis_max_level}.\n\n"
        f"Allowed taxonomy:\n{json.dumps(sorted(allowed_taxonomy), ensure_ascii=False)}\n\n"
        f"Passage:\n{text}"
    )
    response = OpenAI(api_key=api_key).responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    f"You are a precise {profile.study_language} linguist and "
                    "language-learning editor."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        text_format=Analysis,
        reasoning={"effort": "low"},
        store=False,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI did not return structured passage analysis.")
    required = [
        parsed.translation,
        parsed.interpretation,
        parsed.style_explanation,
    ]
    if any(not value.strip() for value in required):
        raise RuntimeError("OpenAI returned incomplete passage analysis.")
    if not parsed.styles or any(style not in allowed_styles for style in parsed.styles):
        raise RuntimeError("OpenAI returned an invalid style classification.")

    candidates: list[AnalysisCandidate] = []
    seen: set[str] = set()
    for candidate in parsed.candidates:
        values = (
            candidate.word,
            candidate.meaning,
            candidate.example_vn,
            candidate.example_en,
            candidate.rationale,
            candidate.everyday_example_vn,
            candidate.everyday_example_en,
            candidate.simple_example_vn,
            candidate.simple_example_en,
        )
        if any(not value.strip() for value in values):
            raise RuntimeError("OpenAI returned an incomplete learning candidate.")
        if not has_complete_ai_taxonomy(candidate.tags):
            raise RuntimeError("OpenAI returned invalid candidate tags.")
        level = next(
            tag.removeprefix("level::")
            for tag in candidate.tags
            if tag.startswith("level::")
        )
        if level not in profile.analysis_levels:
            raise RuntimeError("OpenAI returned a candidate outside the configured level range.")
        if candidate.example_vn.strip() not in text:
            raise RuntimeError("OpenAI returned an example sentence not found in the passage.")
        normalized_examples = {
            candidate.example_vn.strip().casefold(),
            candidate.everyday_example_vn.strip().casefold(),
            candidate.simple_example_vn.strip().casefold(),
        }
        if len(normalized_examples) != 3:
            raise RuntimeError("OpenAI returned duplicate learning examples.")
        key = normalize_headword(candidate.word)
        if not key or key in seen:
            raise RuntimeError("OpenAI returned an empty or duplicate candidate headword.")
        seen.add(key)
        candidates.append(
            AnalysisCandidate(
                word=candidate.word.strip(),
                meaning=candidate.meaning.strip(),
                example_vn=candidate.example_vn.strip(),
                example_en=candidate.example_en.strip(),
                rationale=candidate.rationale.strip(),
                tags=list(candidate.tags),
                card_type=candidate.card_type,
                everyday_example_vn=candidate.everyday_example_vn.strip(),
                everyday_example_en=candidate.everyday_example_en.strip(),
                simple_example_vn=candidate.simple_example_vn.strip(),
                simple_example_en=candidate.simple_example_en.strip(),
            )
        )
    grammar = []
    for point in parsed.grammar:
        if not point.pattern.strip() or not point.explanation.strip():
            raise RuntimeError("OpenAI returned an incomplete grammar point.")
        grammar.append((point.pattern.strip(), point.explanation.strip()))
    return PassageAnalysis(
        translation=parsed.translation.strip(),
        interpretation=parsed.interpretation.strip(),
        styles=list(dict.fromkeys(parsed.styles)),
        style_explanation=parsed.style_explanation.strip(),
        grammar=grammar,
        candidates=candidates,
    )


def known_anki_headwords(
    profile: LanguageProfile = DEFAULT_PROFILE,
    vocabulary_model: str = "Vocabulary",
    grammar_model: str = "Grammar",
) -> tuple[set[str], str | None]:
    models = invoke("modelNames")
    if not isinstance(models, list):
        raise RuntimeError("AnkiConnect returned invalid note types.")
    if vocabulary_model not in models and profile.is_vietnamese and "Vietnamese" in models:
        vocabulary_model = "Vietnamese"
    selected_models = [model for model in (vocabulary_model, grammar_model) if model in models]
    if not selected_models:
        return set(), None
    known: set[str] = set()
    for model in selected_models:
        fields = invoke("modelFieldNames", modelName=model)
        if not isinstance(fields, list):
            raise RuntimeError("AnkiConnect returned invalid note fields.")
        word_field = "Grammar" if model == grammar_model else infer_field_names(fields)["target"]
        if word_field not in fields:
            continue
        escaped_model = model.replace("\\", "\\\\").replace('"', '\\"')
        escaped_deck = profile.deck.replace("\\", "\\\\").replace('"', '\\"')
        note_ids = invoke(
            "findNotes", query=f'note:"{escaped_model}" deck:"{escaped_deck}"'
        )
        if not isinstance(note_ids, list):
            raise RuntimeError("AnkiConnect returned invalid note IDs.")
        notes = invoke("notesInfo", notes=note_ids) if note_ids else []
        if not isinstance(notes, list):
            raise RuntimeError("AnkiConnect returned invalid note details.")
        for note in notes:
            field: Any = note.get("fields", {}).get(word_field, {})
            if isinstance(field, dict):
                value = normalize_headword(html.unescape(str(field.get("value", ""))))
                if value:
                    known.add(value)
    return known, " + ".join(selected_models)
