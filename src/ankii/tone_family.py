from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from ankii.anki import invoke
from ankii.importer import build_note, infer_field_names
from ankii.keychain import get_openai_api_key
from ankii.review import ALLOWED_AI_TAGS, REVIEW_VERSION, has_complete_ai_taxonomy

TONE_NAMES = ("level", "acute", "grave", "hook", "tilde", "dot")
TONE_MARKS = ("", "\u0301", "\u0300", "\u0309", "\u0303", "\u0323")
TONE_LABELS = {
    "level": "ngang",
    "acute": "sắc",
    "grave": "huyền",
    "hook": "hỏi",
    "tilde": "ngã",
    "dot": "nặng",
}
TONE_FIELDS = {name: name.title() for name in TONE_NAMES}
BASE_FIELDS = ("Base", "Dialect Note", "AI Model", "AI Explanation")
FORM_SUFFIXES = ("Form", "Meaning", "Example VN", "Example EN", "Usage", "Enabled")
TONE_MODEL_MARKER = "/* ankii tone-family */"
TONE_MODEL_END = "/* /ankii tone-family */"
LEGACY_TONE_MODEL_MARKERS = (
    "/* yhw2anki tone-family */",
    "/* /yhw2anki tone-family */",
)
VOCABULARY_LINK_FIELD = "Tone Family"
RELATED_WORDS_FIELD = "Related Words"
VOCABULARY_LINK_START = "<!-- ankii tone-family link -->"
VOCABULARY_LINK_END = "<!-- /ankii tone-family link -->"
VOCABULARY_LINK_CSS_START = "/* ankii tone-family link */"
VOCABULARY_LINK_CSS_END = "/* /ankii tone-family link */"
LEGACY_VOCABULARY_LINK_MARKERS = (
    "<!-- yhw2anki tone-family link -->",
    "<!-- /yhw2anki tone-family link -->",
)
LEGACY_VOCABULARY_LINK_CSS_MARKERS = (
    "/* yhw2anki tone-family link */",
    "/* /yhw2anki tone-family link */",
)
RELATED_WORDS_START = "<!-- ankii related-words -->"
RELATED_WORDS_END = "<!-- /ankii related-words -->"
RELATED_WORDS_CSS_START = "/* ankii related-words */"
RELATED_WORDS_CSS_END = "/* /ankii related-words */"
_TONE_COMBINING = {"\u0300", "\u0301", "\u0303", "\u0309", "\u0323"}
_VIETNAMESE_VOWELS = set("aăâeêioôơuưy")
_VIETNAMESE_LETTERS = "a-zăâđêôơư"


@dataclass
class ToneSense:
    meaning: str
    part_of_speech: str
    example_vn: str
    example_en: str


@dataclass
class ToneEntry:
    tone: str
    form: str
    senses: list[ToneSense]
    usage_note: str
    common: bool
    tags: list[str]

    @property
    def meaning(self) -> str:
        return "; ".join(sense.meaning for sense in self.senses)

    @property
    def example_vn(self) -> str:
        return "\n".join(sense.example_vn for sense in self.senses)

    @property
    def example_en(self) -> str:
        return "\n".join(sense.example_en for sense in self.senses)


@dataclass
class ToneFamily:
    base: str
    entries: list[ToneEntry]
    explanation: str
    model: str


def tone_family_to_review(
    family: ToneFamily,
    tone_model: str = "ToneFamily",
    vocabulary_model: str = "Vocabulary",
) -> dict[str, Any]:
    del tone_model  # Accepted for compatibility with older callers.

    def entry_data(entry: ToneEntry) -> dict[str, Any]:
        return {
            "tone": entry.tone,
            "form": entry.form,
            "senses": [vars(sense) for sense in entry.senses],
            "usage_note": entry.usage_note,
            "common": entry.common,
            "tags": entry.tags,
        }

    cards = [
        {
            "word": entry.form,
            "meaning": entry.meaning,
            "example_vn": entry.example_vn,
            "example_en": entry.example_en,
            "tags": [
                "card_type::vocabulary",
                "source::openai",
                "dialect::southern",
                f"tone_family::{family.base}",
                *entry.tags,
            ],
            "ai_explanation": entry.usage_note or family.explanation,
            "approved": True,
            "skip": False,
        }
        for entry in family.entries
        if entry.common
    ]
    return {
        "review_version": REVIEW_VERSION,
        "review_kind": "tone_family",
        "lesson": {
            "public_id": f"tone-family-{family.base}",
            "title": f"Tone family: {family.base}",
            "source_language": "Vietnamese",
            "source_url": "",
        },
        "tone_family": {
            "base": family.base,
            "entries": [entry_data(entry) for entry in family.entries],
            "explanation": family.explanation,
            "ai_model": family.model,
            "vocabulary_model": vocabulary_model,
        },
        "cards": cards,
    }


def tone_family_from_review(review: dict[str, Any]) -> ToneFamily:
    if review.get("review_kind") != "tone_family" or not isinstance(
        review.get("tone_family"), dict
    ):
        raise ValueError("This is not a tone-family review file.")
    data = review["tone_family"]
    try:
        entries = [
            ToneEntry(
                tone=str(item["tone"]),
                form=str(item["form"]),
                senses=[ToneSense(**sense) for sense in item["senses"]],
                usage_note=str(item.get("usage_note", "")),
                common=bool(item["common"]),
                tags=[str(tag) for tag in item.get("tags", [])],
            )
            for item in data["entries"]
        ]
        family = ToneFamily(
            base=normalize_syllable(str(data["base"])),
            entries=entries,
            explanation=str(data.get("explanation", "")),
            model=str(data.get("ai_model", "")),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError("The tone-family review data is malformed.") from exc
    if [entry.tone for entry in family.entries] != list(TONE_NAMES):
        raise ValueError("The tone-family review must contain all six tones in order.")
    expected = tone_variants(family.base)
    if any(entry.form != expected[entry.tone] for entry in family.entries):
        raise ValueError("The tone-family review contains an invalid spelling.")
    return family


def normalize_syllable(value: str) -> str:
    value = unicodedata.normalize("NFD", value.strip().lower())
    value = "".join(char for char in value if char not in _TONE_COMBINING)
    value = unicodedata.normalize("NFC", value)
    if not value or not re.fullmatch(r"[a-zăâđêôơư]+", value):
        raise ValueError("Enter one Vietnamese syllable containing letters only.")
    if not any(char in _VIETNAMESE_VOWELS for char in value):
        raise ValueError("The Vietnamese syllable must contain a vowel.")
    return value


def _tone_vowel_index(base: str) -> int:
    vowels = [index for index, char in enumerate(base) if char in _VIETNAMESE_VOWELS]
    # In qu/gi, u/i acts as part of the initial when another vowel follows.
    if base.startswith("qu") and len(vowels) > 1 and vowels[0] == 1:
        vowels.pop(0)
    if base.startswith("gi") and len(vowels) > 1 and vowels[0] == 1:
        vowels.pop(0)
    if not vowels:
        raise ValueError("The Vietnamese syllable has no tone-bearing vowel.")
    special = [index for index in vowels if base[index] in "ăâêôơư"]
    if special:
        # In ươ, the tone belongs on ơ; other nuclei have one decisive marked vowel.
        return special[-1]
    if len(vowels) == 1:
        return vowels[0]
    has_final_consonant = vowels[-1] < len(base) - 1
    if len(vowels) == 2:
        return vowels[1] if has_final_consonant else vowels[0]
    return vowels[1]


def tone_variants(value: str) -> dict[str, str]:
    base = normalize_syllable(value)
    index = _tone_vowel_index(base)
    decomposed_vowel = unicodedata.normalize("NFD", base[index])
    variants: dict[str, str] = {}
    for name, mark in zip(TONE_NAMES, TONE_MARKS, strict=True):
        chars = list(base)
        chars[index] = unicodedata.normalize("NFC", decomposed_vowel + mark)
        variants[name] = "".join(chars)
    return variants


def generate_tone_family(syllable: str, model: str) -> ToneFamily:
    base = normalize_syllable(syllable)
    expected = tone_variants(base)
    api_key, _source = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key was found. Run 'ankii key set' or export OPENAI_API_KEY."
        )
    try:
        from openai import OpenAI
        from pydantic import BaseModel, Field
    except ImportError as exc:
        raise RuntimeError(
            'AI support is not installed. Run: python -m pip install -e ".[ai]"'
        ) from exc

    class GeneratedSense(BaseModel):
        meaning: str
        part_of_speech: str
        example_vn: str
        example_en: str

    class GeneratedEntry(BaseModel):
        tone: str
        form: str
        senses: list[GeneratedSense] = Field(max_length=2)
        usage_note: str = ""
        common: bool
        tags: list[str]

    class GeneratedFamily(BaseModel):
        entries: list[GeneratedEntry]
        explanation: str = ""

    response = OpenAI(api_key=api_key).responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "You are a careful Vietnamese lexicographer for a Southern Vietnamese learner. "
                    "Use standard spelling. Prefer common modern standalone words; mark obsolete, "
                    "rare, invalid, or compound-only forms common=false. Do not invent meanings."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Analyze this tone family: {base}. Return exactly these six entries in this "
                    f"order and with these exact spellings: {expected}. For common entries give "
                    "one or two distinct senses. Each sense needs a concise English gloss, part of "
                    "speech, and a short natural Vietnamese example containing the exact form with "
                    "a faithful English translation. Also choose exactly one allowed "
                    "part_of_speech, "
                    "topic, register, and level tag from this allowed taxonomy: "
                    f"{json.dumps(sorted(ALLOWED_AI_TAGS), ensure_ascii=False)}. For "
                    "uncommon entries, return no senses or taxonomy tags and explain why in the "
                    "usage note. Mention material Southern usage differences only."
                ),
            },
        ],
        text_format=GeneratedFamily,
        reasoning={"effort": "low"},
        store=False,
    )
    parsed = response.output_parsed
    if parsed is None or len(parsed.entries) != len(TONE_NAMES):
        raise RuntimeError("OpenAI did not return all six tone forms.")
    entries: list[ToneEntry] = []
    for tone, item in zip(TONE_NAMES, parsed.entries, strict=True):
        if item.tone != tone or unicodedata.normalize("NFC", item.form) != expected[tone]:
            raise RuntimeError(f"OpenAI returned an unexpected {tone} form.")
        senses = [
            ToneSense(
                meaning=sense.meaning.strip(),
                part_of_speech=sense.part_of_speech.strip(),
                example_vn=sense.example_vn.strip(),
                example_en=sense.example_en.strip(),
            )
            for sense in item.senses
        ]
        if len(senses) > 2:
            raise RuntimeError(f"OpenAI returned too many meanings for {item.form}.")
        meanings = [sense.meaning for sense in senses]
        if len(meanings) != len(set(meaning.casefold() for meaning in meanings)):
            raise RuntimeError(f"OpenAI returned duplicate meanings for {item.form}.")
        if item.common:
            if not senses or not has_complete_ai_taxonomy(item.tags):
                raise RuntimeError(f"OpenAI returned incomplete lexical data for {item.form}.")
            form_pattern = (
                rf"(?<![{_VIETNAMESE_LETTERS}]){re.escape(item.form)}(?![{_VIETNAMESE_LETTERS}])"
            )
            for sense in senses:
                if not all(
                    (sense.meaning, sense.part_of_speech, sense.example_vn, sense.example_en)
                ):
                    raise RuntimeError(f"OpenAI returned an incomplete sense for {item.form}.")
                if not re.search(form_pattern, sense.example_vn, flags=re.IGNORECASE):
                    raise RuntimeError(f"OpenAI example does not contain {item.form}.")
        elif senses or item.tags:
            raise RuntimeError(f"OpenAI returned lexical content for uncommon form {item.form}.")
        entries.append(
            ToneEntry(
                tone=tone,
                form=expected[tone],
                senses=senses,
                usage_note=item.usage_note.strip(),
                common=item.common,
                tags=list(item.tags),
            )
        )
    return ToneFamily(base, entries, parsed.explanation.strip(), model)


def tone_family_fields() -> list[str]:
    fields = list(BASE_FIELDS)
    for tone in TONE_NAMES:
        prefix = TONE_FIELDS[tone]
        fields.extend(f"{prefix} {suffix}" for suffix in FORM_SUFFIXES)
    return fields


def _family_table() -> str:
    rows = []
    for tone in TONE_NAMES:
        prefix = TONE_FIELDS[tone]
        rows.append(
            f'<tr class="tone-{tone} {{{{^{prefix} Enabled}}}}tone-muted{{{{/{prefix} Enabled}}}}">'
            f'<th>{TONE_LABELS[tone]}</th><td class="tone-form">{{{{{prefix} Form}}}}</td>'
            f"<td><div>{{{{{prefix} Meaning}}}}{{{{^{prefix} Meaning}}}}"
            f"{{{{{prefix} Usage}}}}{{{{/{prefix} Meaning}}}}</div>"
            f'{{{{#{prefix} Example VN}}}}<div class="table-example">'
            f'{{{{{prefix} Example VN}}}}</div><div class="translation">'
            f"{{{{{prefix} Example EN}}}}</div>{{{{/{prefix} Example VN}}}}</td></tr>"
        )
    return '<table class="tone-table"><tbody>' + "".join(rows) + "</tbody></table>"


def tone_family_templates() -> dict[str, dict[str, str]]:
    table = _family_table()
    return {
        "Family Recap": {
            "Front": (
                '<div class="direction">Recall the complete tone family</div>'
                '<div class="base">{{Base}}</div>'
            ),
            "Back": "{{FrontSide}}" + table + '<div class="dialect">{{Dialect Note}}</div>',
        }
    }


TONE_CSS = f"""{TONE_MODEL_MARKER}
.card {{
  box-sizing: border-box; max-width: 720px; margin: 0 auto; padding: 26px 18px;
  background: #faf8f3; color: #252525;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  text-align: center;
}}
.direction {{
  color: #777; font-size: 12px; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase;
}}
.meaning {{ margin-top: 18px; font-size: 28px; font-weight: 650; }}
.pos {{ color: #777; margin-top: 5px; }}
.base {{ margin-top: 22px; font-size: 48px; font-weight: 750; }}
.answer {{ margin: 24px 0; padding-top: 20px; border-top: 1px solid #d9d2c3; }}
.target {{ font-size: 52px; font-weight: 800; }}
.example {{ margin-top: 12px; font-size: 21px; }}
.translation, .usage, .dialect {{ margin-top: 7px; color: #686868; }}
.tone-table {{
  width: 100%; margin: 24px 0 0; border-collapse: collapse; text-align: left;
}}
.tone-table th, .tone-table td {{
  padding: 9px 8px; border-bottom: 1px solid #ded8cb;
}}
.tone-table th {{ width: 18%; text-transform: capitalize; }}
.tone-form {{ width: 18%; font-size: 1.25em; font-weight: 750; }}
.tone-muted {{ opacity: .38; }}
.tone-level {{ color: #28666e; }}
.tone-acute {{ color: #b23a2b; }}
.tone-grave {{ color: #7251a1; }}
.tone-hook {{ color: #a36316; }}
.tone-tilde {{ color: #167653; }}
.tone-dot {{ color: #45505e; }}
.nightMode .card {{ background: #242424; color: #eee; }}
.nightMode .translation, .nightMode .usage, .nightMode .dialect,
.nightMode .pos, .nightMode .direction {{ color: #bbb; }}
@media(max-width: 480px) {{
  .card {{ padding: 20px 10px; }}
  .base, .target {{ font-size: 42px; }}
  .tone-table th, .tone-table td {{ padding: 7px 4px; }}
}}
/* /ankii tone-family */"""


def _replace_css_block(css: str) -> str:
    for start, end in (
        (TONE_MODEL_MARKER, TONE_MODEL_END),
        LEGACY_TONE_MODEL_MARKERS,
    ):
        if start in css and end in css:
            before, rest = css.split(start, 1)
            _old, after = rest.split(end, 1)
            return f"{before.rstrip()}\n\n{TONE_CSS}\n{after.lstrip()}".strip()
    return f"{css.rstrip()}\n\n{TONE_CSS}\n".lstrip()


def setup_tone_family_model(model: str = "ToneFamily") -> bool:
    models = list(invoke("modelNames"))
    templates = tone_family_templates()
    if model not in models:
        invoke(
            "createModel",
            modelName=model,
            inOrderFields=tone_family_fields(),
            cardTemplates=[{"Name": name, **sides} for name, sides in templates.items()],
            css=TONE_CSS,
        )
        return True
    existing_fields = list(invoke("modelFieldNames", modelName=model))
    styling = invoke("modelStyling", modelName=model)
    css = str(styling.get("css", ""))
    managed_markers = (TONE_MODEL_MARKER, LEGACY_TONE_MODEL_MARKERS[0])
    if not any(marker in css for marker in managed_markers):
        raise ValueError(
            f"Anki note type {model!r} already exists but is not managed by ankii. "
            "Choose another --model name."
        )
    for field in tone_family_fields():
        if field not in existing_fields:
            invoke("modelFieldAdd", modelName=model, fieldName=field)
    existing_templates = invoke("modelTemplates", modelName=model)
    legacy_names = {f"{label.title()} Recall" for label in TONE_LABELS.values()} | {
        "Family Overview"
    }
    recap = templates["Family Recap"]
    if existing_templates.get("Family Recap") != recap:
        invoke(
            "modelTemplateAdd",
            modelName=model,
            template={"Name": "Family Recap", **recap},
        )
    for template_name in sorted(legacy_names & set(existing_templates)):
        invoke("modelTemplateRemove", modelName=model, templateName=template_name)
    updated_css = _replace_css_block(css)
    if updated_css != css:
        invoke("updateModelStyling", model={"name": model, "css": updated_css})
    return False


def build_tone_family_note(family: ToneFamily, deck: str, model: str) -> dict[str, Any]:
    fields: dict[str, str] = {
        "Base": html.escape(family.base),
        "Dialect Note": (
            "Southern Vietnamese often pronounces hỏi and ngã alike; their standard spellings "
            "and meanings remain distinct."
        ),
        "AI Model": html.escape(family.model),
        "AI Explanation": html.escape(family.explanation),
    }
    for entry in family.entries:
        prefix = TONE_FIELDS[entry.tone]
        values = {
            "Form": entry.form,
            "Meaning": entry.meaning,
            "Example VN": entry.example_vn,
            "Example EN": entry.example_en,
            "Usage": entry.usage_note,
            "Enabled": "1" if entry.common else "",
        }
        fields.update(
            {
                f"{prefix} {key}": html.escape(value).replace("\n", "<br>")
                for key, value in values.items()
            }
        )
    return {
        "deckName": deck,
        "modelName": model,
        "fields": fields,
        "tags": [
            "card_type::tone_family",
            "source::openai",
            "dialect::southern",
            f"tone_base::{family.base}",
        ],
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }


def tone_family_from_anki_note(note: dict[str, Any]) -> ToneFamily:
    """Reconstruct a legacy tone family from a ToneFamily Anki note."""

    raw_fields = note.get("fields", {})

    def field(name: str) -> str:
        raw = raw_fields.get(name, {})
        value = raw.get("value", "") if isinstance(raw, dict) else ""
        return html.unescape(re.sub(r"<br\s*/?>", "\n", str(value), flags=re.I)).strip()

    base = normalize_syllable(field("Base"))
    entries: list[ToneEntry] = []
    for tone in TONE_NAMES:
        prefix = TONE_FIELDS[tone]
        meanings = [item.strip() for item in field(f"{prefix} Meaning").split(";") if item.strip()]
        examples_vn = field(f"{prefix} Example VN").splitlines()
        examples_en = field(f"{prefix} Example EN").splitlines()
        senses = [
            ToneSense(
                meaning=meaning,
                part_of_speech="",
                example_vn=examples_vn[index] if index < len(examples_vn) else "",
                example_en=examples_en[index] if index < len(examples_en) else "",
            )
            for index, meaning in enumerate(meanings)
        ]
        entries.append(
            ToneEntry(
                tone=tone,
                form=field(f"{prefix} Form") or tone_variants(base)[tone],
                senses=senses,
                usage_note=field(f"{prefix} Usage"),
                common=bool(field(f"{prefix} Enabled")),
                tags=[],
            )
        )
    return ToneFamily(base, entries, field("AI Explanation"), field("AI Model"))


def related_words_html(family: ToneFamily, current_form: str) -> str:
    """Render a complete, escaped tone-family table for one vocabulary note."""

    rows = []
    for entry in family.entries:
        classes = [f"related-tone-{entry.tone}"]
        if not entry.common:
            classes.append("related-word-muted")
        if unicodedata.normalize("NFC", entry.form) == unicodedata.normalize("NFC", current_form):
            classes.append("related-word-current")
        details = []
        if entry.meaning:
            details.append(f'<div class="related-word-meaning">{html.escape(entry.meaning)}</div>')
        if entry.usage_note:
            details.append(f'<div class="related-word-usage">{html.escape(entry.usage_note)}</div>')
        if not entry.common and not entry.usage_note:
            details.append('<div class="related-word-usage">Not a common standalone word</div>')
        for sense in entry.senses:
            if sense.example_vn:
                example = html.escape(sense.example_vn)
                translation = (
                    f'<div class="related-word-translation">{html.escape(sense.example_en)}</div>'
                    if sense.example_en
                    else ""
                )
                details.append(f'<div class="related-word-example">{example}{translation}</div>')
        rows.append(
            f'<tr class="{" ".join(classes)}"><th>{html.escape(TONE_LABELS[entry.tone])}</th>'
            f'<td class="related-word-form">{html.escape(entry.form)}</td>'
            f"<td>{''.join(details)}</td></tr>"
        )
    dialect = (
        "Southern Vietnamese often pronounces hỏi and ngã alike; their standard spellings "
        "and meanings remain distinct."
    )
    return (
        '<table class="related-words-table"><tbody>'
        + "".join(rows)
        + '</tbody></table><div class="related-words-dialect">'
        + dialect
        + "</div>"
    )


VOCABULARY_LINK_TEMPLATE = f"""{VOCABULARY_LINK_START}
{{{{#Tone Family}}}}<div class="yhw-tone-family-link">
<span class="yhw-tone-family-label">Related</span>{{{{Tone Family}}}}
</div>{{{{/Tone Family}}}}
{VOCABULARY_LINK_END}"""

VOCABULARY_LINK_CSS = f"""{VOCABULARY_LINK_CSS_START}
.yhw-tone-family-link {{
  display: flex; align-items: center; justify-content: center; gap: 7px;
  margin: 14px auto 0; font-size: .78em;
}}
.yhw-tone-family-label {{
  color: #999; font-weight: 650; letter-spacing: .04em; text-transform: uppercase;
}}
.yhw-tone-family-link a {{
  padding: 4px 9px; border: 1px solid rgba(127,127,127,.28); border-radius: 999px;
  color: #666; text-decoration: none;
}}
.nightMode .yhw-tone-family-label {{ color: #888; }}
.nightMode .yhw-tone-family-link a {{ color: #bbb; border-color: rgba(255,255,255,.18); }}
{VOCABULARY_LINK_CSS_END}"""

RELATED_WORDS_TEMPLATE = f"""{RELATED_WORDS_START}
{{{{#Related Words}}}}
<details class="related-words">
  <summary>Related words</summary>
  <div class="related-words-content">{{{{Related Words}}}}</div>
</details>
{{{{/Related Words}}}}
{RELATED_WORDS_END}"""

RELATED_WORDS_CSS = f"""{RELATED_WORDS_CSS_START}
.related-words {{
  max-width: 680px; margin: 18px auto 0; border: 1px solid rgba(127,127,127,.28);
  border-radius: 10px; background: rgba(127,127,127,.06); text-align: left;
}}
.related-words summary {{
  padding: 11px 14px; cursor: pointer; color: #666; font-size: .82em;
  font-weight: 700; letter-spacing: .04em; text-transform: uppercase;
}}
.related-words-content {{ padding: 0 12px 12px; }}
.related-words-table {{ width: 100%; border-collapse: collapse; }}
.related-words-table th, .related-words-table td {{
  padding: 9px 7px; border-top: 1px solid rgba(127,127,127,.22); vertical-align: top;
}}
.related-words-table th {{ width: 17%; text-transform: capitalize; }}
.related-word-form {{ width: 19%; font-size: 1.18em; font-weight: 750; }}
.related-word-current {{ background: rgba(214,155,53,.15); }}
.related-word-current .related-word-form::after {{ content: " •"; color: #b17813; }}
.related-word-muted {{ opacity: .42; }}
.related-word-example {{ margin-top: 6px; }}
.related-word-translation, .related-word-usage, .related-words-dialect {{
  margin-top: 4px; color: #777; font-size: .88em; font-style: italic;
}}
.related-words-dialect {{ padding: 10px 7px 0; }}
.related-tone-level {{ color: #28666e; }}
.related-tone-acute {{ color: #b23a2b; }}
.related-tone-grave {{ color: #7251a1; }}
.related-tone-hook {{ color: #a36316; }}
.related-tone-tilde {{ color: #167653; }}
.related-tone-dot {{ color: #45505e; }}
.nightMode .related-words {{ background: rgba(255,255,255,.05); }}
.nightMode .related-words summary, .nightMode .related-word-translation,
.nightMode .related-word-usage, .nightMode .related-words-dialect {{ color: #bbb; }}
@media(max-width: 480px) {{
  .related-words-content {{ padding: 0 6px 8px; }}
  .related-words-table th, .related-words-table td {{ padding: 7px 4px; }}
}}
{RELATED_WORDS_CSS_END}"""


def _remove_managed_block(value: str, blocks: tuple[tuple[str, str], ...]) -> str:
    for start, end in blocks:
        while start in value and end in value:
            before, rest = value.split(start, 1)
            _old, after = rest.split(end, 1)
            value = f"{before.rstrip()}\n{after.lstrip()}"
    return value


def setup_vocabulary_related_words(model: str = "Vocabulary") -> None:
    """Add the optional Related Words field and managed disclosure to a model."""

    models = list(invoke("modelNames"))
    if model not in models:
        raise ValueError(
            f"Anki vocabulary note type {model!r} does not exist. "
            "Run 'ankii anki setup-note-types' first."
        )
    fields = list(invoke("modelFieldNames", modelName=model))
    if RELATED_WORDS_FIELD not in fields:
        invoke("modelFieldAdd", modelName=model, fieldName=RELATED_WORDS_FIELD)
    templates = invoke("modelTemplates", modelName=model)
    updated = {name: dict(value) for name, value in templates.items()}
    template_blocks = (
        (RELATED_WORDS_START, RELATED_WORDS_END),
        (VOCABULARY_LINK_START, VOCABULARY_LINK_END),
        LEGACY_VOCABULARY_LINK_MARKERS,
    )
    for value in updated.values():
        back = _remove_managed_block(value["Back"], template_blocks)
        value["Back"] = f"{back.rstrip()}\n\n{RELATED_WORDS_TEMPLATE}\n"
    if updated != templates:
        invoke("updateModelTemplates", model={"name": model, "templates": updated})
    styling = invoke("modelStyling", modelName=model)
    css = str(styling.get("css", ""))
    updated_css = _remove_managed_block(
        css,
        (
            (RELATED_WORDS_CSS_START, RELATED_WORDS_CSS_END),
            (VOCABULARY_LINK_CSS_START, VOCABULARY_LINK_CSS_END),
            LEGACY_VOCABULARY_LINK_CSS_MARKERS,
        ),
    )
    updated_css = f"{updated_css.rstrip()}\n\n{RELATED_WORDS_CSS}\n"
    if updated_css != css:
        invoke("updateModelStyling", model={"name": model, "css": updated_css})


def setup_vocabulary_tone_link(model: str = "Vocabulary") -> None:
    """Deprecated compatibility wrapper for the embedded related-words setup."""
    setup_vocabulary_related_words(model)


def tone_family_link(base: str, parent_note_id: int) -> str:
    query = quote(f"nid:{parent_note_id}", safe="")
    return (
        f'<a href="anki://x-callback-url/search?query={query}">Tone family: {html.escape(base)}</a>'
    )


def build_tone_vocabulary_note(
    entry: ToneEntry,
    family: ToneFamily,
    deck: str,
    model: str,
    available_fields: set[str],
    parent_note_id: int | None = None,
) -> dict[str, Any]:
    if not entry.common:
        raise ValueError(f"Cannot build a Vocabulary note for uncommon form {entry.form!r}.")
    field_names = infer_field_names(list(available_fields))
    card = {
        "word": entry.form,
        "meaning": entry.meaning,
        "example_vn": entry.example_vn,
        "example_en": entry.example_en,
        "ai_explanation": entry.usage_note or family.explanation,
        "tags": [
            "card_type::vocabulary",
            "source::openai",
            "dialect::southern",
            f"tone_family::{family.base}",
            *entry.tags,
        ],
    }
    note = build_note(
        card,
        {"public_id": "tone-family", "title": f"Tone family: {family.base}"},
        deck,
        model,
        available_fields,
        field_names,
    )
    if RELATED_WORDS_FIELD in available_fields:
        note["fields"][RELATED_WORDS_FIELD] = related_words_html(family, entry.form)
    return note
