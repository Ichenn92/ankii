from __future__ import annotations

import html
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ankii.keychain import get_openai_api_key
from ankii.maintenance import notes_for_model
from ankii.review import ALLOWED_AI_TAGS, has_complete_ai_taxonomy
from ankii.settings import DEFAULT_PROFILE, LanguageProfile

IGNORE_VERSION = 1
BATCH_SIZE = 20


@dataclass(frozen=True)
class GrammarSuggestion:
    pattern: str
    explanation: str
    example_vn: str
    example_en: str
    everyday_example_vn: str
    everyday_example_en: str
    tags: list[str]
    source_note_id: int
    source_word: str
    source: str


def normalize_pattern(value: str) -> str:
    value = value.replace("…", "...").replace("⋯", "...")
    return re.sub(r"\s+", " ", value.casefold().strip())


def field_value(note: dict[str, Any], field: str) -> str:
    value = note.get("fields", {}).get(field, {})
    return html.unescape(str(value.get("value", ""))).strip() if isinstance(value, dict) else ""


def example_lines(value: str) -> list[str]:
    value = re.sub(r"(?i)<br\s*/?>", "\n", value)
    value = re.sub(r"(?i)</(?:div|p|li)>", "\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    return [html.unescape(line).strip() for line in value.splitlines() if line.strip()]


def vocabulary_inputs(
    model: str, profile: LanguageProfile = DEFAULT_PROFILE
) -> tuple[list[dict[str, Any]], int]:
    notes = (
        notes_for_model(model)
        if profile == DEFAULT_PROFILE
        else notes_for_model(model, profile.deck)
    )
    inputs: list[dict[str, Any]] = []
    skipped = 0
    for note in notes:
        target_lines = example_lines(
            field_value(note, "Example Target") or field_value(note, "Example VN")
        )
        native_lines = example_lines(
            field_value(note, "Example Native") or field_value(note, "Example EN")
        )
        if not target_lines:
            skipped += 1
            continue
        if profile == DEFAULT_PROFILE:
            pairs = [
                {
                    "vietnamese": line,
                    "english": native_lines[index] if index < len(native_lines) else "",
                }
                for index, line in enumerate(target_lines)
            ]
        else:
            pairs = [
                {
                    "target": line,
                    "native": native_lines[index] if index < len(native_lines) else "",
                }
                for index, line in enumerate(target_lines)
            ]
        inputs.append(
            {
                "note_id": int(note["noteId"]),
                "word": field_value(note, "Target") or field_value(note, "Vietnamese"),
                "source": field_value(note, "Source"),
                "examples": pairs,
            }
        )
    return inputs, skipped


def grammar_patterns(model: str, profile: LanguageProfile = DEFAULT_PROFILE) -> set[str]:
    return {
        normalize_pattern(field_value(note, "Grammar"))
        for note in (
            notes_for_model(model)
            if profile == DEFAULT_PROFILE
            else notes_for_model(model, profile.deck)
        )
        if field_value(note, "Grammar")
    }


def load_ignored(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid grammar ignore JSON in {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("ignore_version") != IGNORE_VERSION:
        raise ValueError(f"{path} is not a supported grammar ignore file.")
    patterns = data.get("patterns")
    if not isinstance(patterns, dict) or any(
        not isinstance(key, str) or not isinstance(value, dict)
        for key, value in patterns.items()
    ):
        raise ValueError(f"{path} has invalid ignored patterns.")
    return patterns


def save_ignored(path: Path, patterns: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(
                {"ignore_version": IGNORE_VERSION, "patterns": patterns},
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def add_rejections(
    existing: dict[str, dict[str, Any]], suggestions: list[GrammarSuggestion]
) -> dict[str, dict[str, Any]]:
    updated = dict(existing)
    timestamp = datetime.now(UTC).isoformat()
    for item in suggestions:
        updated[normalize_pattern(item.pattern)] = {
            "pattern": item.pattern,
            "source_note_id": item.source_note_id,
            "source_word": item.source_word,
            "rejected_at": timestamp,
        }
    return updated


def _suggest_batch(
    batch: list[dict[str, Any]],
    known_patterns: set[str],
    model: str,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> list[GrammarSuggestion]:
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

    class Candidate(BaseModel):
        pattern: str
        explanation: str
        example_vn: str
        example_en: str
        everyday_example_vn: str
        everyday_example_en: str
        tags: list[str]
        source_note_id: int

    class Result(BaseModel):
        candidates: list[Candidate]

    allowed_taxonomy = {
        tag
        for tag in ALLOWED_AI_TAGS
        if not tag.startswith("level::")
        or tag.removeprefix("level::") in profile.analysis_levels
    }
    prompt = (
        f"Find every identifiable, reusable {profile.study_language} grammar structure evidenced "
        f"by these vocabulary-note examples, from {profile.analysis_min_level} through "
        f"{profile.analysis_max_level}: particles, classifiers, word order, "
        "sentence frames, and common constructions. Exclude arbitrary lexical collocations and "
        "one-off poetic wording. Return no known pattern. The source example must exactly match "
        f"one supplied {profile.study_language} line and source_note_id. Use its paired "
        f"{profile.native_language} line exactly "
        "when present; otherwise provide a faithful translation. Write one additional natural, "
        f"non-poetic {profile.analysis_max_level} everyday example and faithful "
        "translation. Canonicalize patterns with slots such as 'có … thì …'. Choose exactly one "
        "taxonomy tag for part_of_speech, topic, register, and level; part_of_speech must be "
        "part_of_speech::other.\n\n"
        f"Allowed taxonomy:\n{json.dumps(sorted(allowed_taxonomy), ensure_ascii=False)}\n\n"
        f"Known normalized patterns:\n{json.dumps(sorted(known_patterns), ensure_ascii=False)}\n\n"
        f"Vocabulary notes:\n{json.dumps(batch, ensure_ascii=False)}"
    )
    response = OpenAI(api_key=api_key).responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    f"You identify evidenced {profile.study_language} grammar for flashcards."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        text_format=Result,
        reasoning={"effort": "low"},
        store=False,
    )
    parsed = response.output_parsed
    if parsed is None:
        raise RuntimeError("OpenAI did not return structured grammar suggestions.")
    by_id = {item["note_id"]: item for item in batch}
    suggestions: list[GrammarSuggestion] = []
    seen: set[str] = set()
    for candidate in parsed.candidates:
        source = by_id.get(candidate.source_note_id)
        if source is None:
            raise RuntimeError("OpenAI returned an unknown source note ID.")
        pairs = {
            str(item.get("target", item.get("vietnamese", ""))): str(
                item.get("native", item.get("english", ""))
            )
            for item in source["examples"]
        }
        values = (
            candidate.pattern,
            candidate.explanation,
            candidate.example_vn,
            candidate.example_en,
            candidate.everyday_example_vn,
            candidate.everyday_example_en,
        )
        if any(not value.strip() for value in values):
            raise RuntimeError("OpenAI returned an incomplete grammar suggestion.")
        if candidate.example_vn not in pairs:
            raise RuntimeError("OpenAI returned a grammar example not found in its source note.")
        paired_english = pairs[candidate.example_vn]
        if paired_english and candidate.example_en.strip() != paired_english:
            raise RuntimeError("OpenAI changed the source example translation.")
        if candidate.everyday_example_vn.strip() == candidate.example_vn.strip():
            raise RuntimeError("OpenAI reused the source sentence as the everyday example.")
        if not has_complete_ai_taxonomy(candidate.tags):
            raise RuntimeError("OpenAI returned invalid grammar taxonomy tags.")
        level = next(
            tag.removeprefix("level::")
            for tag in candidate.tags
            if tag.startswith("level::")
        )
        if level not in profile.analysis_levels:
            raise RuntimeError("OpenAI returned grammar outside the configured level range.")
        if "part_of_speech::other" not in candidate.tags:
            raise RuntimeError("OpenAI returned an invalid grammar part-of-speech tag.")
        key = normalize_pattern(candidate.pattern)
        if not key or key in known_patterns or key in seen:
            continue
        seen.add(key)
        suggestions.append(
            GrammarSuggestion(
                pattern=candidate.pattern.strip(),
                explanation=candidate.explanation.strip(),
                example_vn=candidate.example_vn.strip(),
                example_en=candidate.example_en.strip() or paired_english,
                everyday_example_vn=candidate.everyday_example_vn.strip(),
                everyday_example_en=candidate.everyday_example_en.strip(),
                tags=list(candidate.tags),
                source_note_id=candidate.source_note_id,
                source_word=str(source["word"]),
                source=str(source["source"]),
            )
        )
    return suggestions


def discover_grammar(
    vocabulary_model: str,
    grammar_model: str,
    ai_model: str,
    ignored: set[str],
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> tuple[list[GrammarSuggestion], dict[str, int]]:
    inputs, skipped = (
        vocabulary_inputs(vocabulary_model)
        if profile == DEFAULT_PROFILE
        else vocabulary_inputs(vocabulary_model, profile)
    )
    known = (
        grammar_patterns(grammar_model)
        if profile == DEFAULT_PROFILE
        else grammar_patterns(grammar_model, profile)
    ) | ignored
    suggestions: list[GrammarSuggestion] = []
    for start in range(0, len(inputs), BATCH_SIZE):
        batch = inputs[start : start + BATCH_SIZE]
        found = (
            _suggest_batch(batch, known, ai_model)
            if profile == DEFAULT_PROFILE
            else _suggest_batch(batch, known, ai_model, profile)
        )
        suggestions.extend(found)
        known.update(normalize_pattern(item.pattern) for item in found)
    return suggestions, {
        "notes": len(inputs) + skipped,
        "analyzed": len(inputs),
        "skipped": skipped,
        "suggestions": len(suggestions),
    }
