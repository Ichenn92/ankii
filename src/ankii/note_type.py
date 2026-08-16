from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from ankii.anki import invoke
from ankii.review import load_review
from ankii.tone_family import (
    LEGACY_VOCABULARY_LINK_CSS_MARKERS,
    LEGACY_VOCABULARY_LINK_MARKERS,
    RELATED_WORDS_CSS,
    RELATED_WORDS_CSS_END,
    RELATED_WORDS_CSS_START,
    RELATED_WORDS_END,
    RELATED_WORDS_FIELD,
    RELATED_WORDS_START,
    RELATED_WORDS_TEMPLATE,
    VOCABULARY_LINK_CSS_END,
    VOCABULARY_LINK_CSS_START,
    VOCABULARY_LINK_END,
    VOCABULARY_LINK_START,
)

SOURCE_EXAMPLE_FIELDS = ("Example Target", "Example Native")
EXAMPLE_FIELDS = SOURCE_EXAMPLE_FIELDS
VOCABULARY_AUDIO_FIELDS = ("Target Audio", "Example Audio")
LEGACY_EXAMPLE_FIELDS = ("Example VN", "Example EN")
LEGACY_FIELDS = {
    "Example Target": ("Example VN", "ExampleVN", "Example", "Examples"),
    "Example Native": ("Example EN", "ExampleEN", "Example Translation"),
}
EXAMPLE_MARKERS = ("<!-- ankii examples -->", "<!-- /ankii examples -->")
SOURCE_MARKERS = ("<!-- ankii source -->", "<!-- /ankii source -->")
EXAMPLE_CSS_MARKERS = ("/* ankii examples */", "/* /ankii examples */")
SOURCE_CSS_MARKERS = ("/* ankii source */", "/* /ankii source */")
TARGET_AUDIO_MARKERS = ("<!-- ankii target audio -->", "<!-- /ankii target audio -->")
INLINE_EXAMPLE_AUDIO_MARKERS = (
    "<!-- ankii inline example audio -->",
    "<!-- /ankii inline example audio -->",
)
LEGACY_EXAMPLE_MARKERS = (
    "<!-- yhw2anki examples -->",
    "<!-- /yhw2anki examples -->",
)
LEGACY_SOURCE_MARKERS = ("<!-- yhw2anki source -->", "<!-- /yhw2anki source -->")
LEGACY_EXAMPLE_CSS_MARKERS = (
    "/* yhw2anki examples */",
    "/* /yhw2anki examples */",
)
LEGACY_SOURCE_CSS_MARKERS = (
    "/* yhw2anki source */",
    "/* /yhw2anki source */",
)

EXAMPLE_TEMPLATE = """<!-- ankii examples -->
{{#Example Target}}
<div class="yhw-example">
  <div class="yhw-example-target-row">
    <div class="yhw-example-vn">{{Example Target}}</div>
    {{#Example Audio}}<div class="yhw-example-audio">{{Example Audio}}</div>{{/Example Audio}}
  </div>
  {{#Example Native}}<div class="yhw-example-en">{{Example Native}}</div>{{/Example Native}}
</div>
{{/Example Target}}
<!-- /ankii examples -->"""

TARGET_AUDIO_TEMPLATE = """<!-- ankii target audio -->
{{#Target Audio}}<span class="yhw-target-audio">{{Target Audio}}</span>{{/Target Audio}}
<!-- /ankii target audio -->"""

INLINE_EXAMPLE_AUDIO_TEMPLATE = """<!-- ankii inline example audio -->
{{#Example Audio}}<span class="yhw-example-audio">{{Example Audio}}</span>{{/Example Audio}}
<!-- /ankii inline example audio -->"""

SOURCE_TEMPLATE = r"""<!-- ankii source -->
{{#Source}}
<div class="yhw-source-card">
  <div class="yhw-source-copy">
    <div class="yhw-source-label">Source</div>
    <div class="yhw-source-title"></div>
  </div>
  <div class="yhw-source-actions"></div>
  <span class="yhw-source-raw">{{Source}}</span>
</div>
<script>
(() => {
  const cards = document.querySelectorAll('.yhw-source-card:not([data-ready])');
  const icons = {
    youtube: `<svg viewBox="0 0 24 24" aria-hidden="true">
      <path fill="#ff0033" d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6
        12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31 31 0 0 0 0 12a31 31 0 0 0
        .5 5.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0
        2.1-2.1A31 31 0 0 0 24 12a31 31 0 0 0-.5-5.8Z"/>
      <path fill="#fff" d="m9.6 15.6 6.3-3.6-6.3-3.6Z"/>
    </svg>`,
    spotify: `<svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="12" fill="#1ed760"/>
      <path fill="none" stroke="#111" stroke-linecap="round" stroke-width="1.8"
        d="M5.3 9.1c4.5-1.3 9.7-.9 13.5 1.1M6.2 12.7c3.8-1 8.2-.7
        11.6.9M7.1 16c3.1-.8 6.5-.5 9.4.7"/>
    </svg>`
  };

  cards.forEach((card) => {
    card.dataset.ready = 'true';
    const value = card.querySelector('.yhw-source-raw').textContent.trim();
    const match = value.match(/^(.*?)(?:\s+—\s+)?(https?:\/\/\S+)$/i);
    const title = match ? match[1].trim() : value;
    const url = match ? match[2] : '';
    card.querySelector('.yhw-source-title').textContent = title || url;

    if (!url) {
      return;
    }
    const actions = card.querySelector('.yhw-source-actions');
    const makeLink = (href, label, className = '') => {
      const link = document.createElement('a');
      link.className = `yhw-source-link ${className}`.trim();
      link.href = href;
      link.textContent = label;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      actions.appendChild(link);
      return link;
    };
    let service = '';
    let appUrl = '';
    try {
      const parsed = new URL(url);
      const host = parsed.hostname.replace(/^www\./, '');
      if (host === 'youtu.be' || host.endsWith('youtube.com')) {
        service = 'youtube';
        const videoId = host === 'youtu.be'
          ? parsed.pathname.split('/').filter(Boolean)[0]
          : parsed.searchParams.get('v');
        if (videoId) appUrl = `youtube://watch?v=${encodeURIComponent(videoId)}`;
      }
      if (host === 'spotify.com' || host.endsWith('.spotify.com')) {
        service = 'spotify';
        const parts = parsed.pathname.split('/').filter(Boolean);
        if (parts.length >= 2) appUrl = `spotify:${parts[0]}:${parts[1]}`;
      }
    } catch (_) {}
    if (service) {
      if (appUrl) {
        const appLink = makeLink(appUrl, '', 'yhw-source-app');
        appLink.innerHTML = `${icons[service]}<span>App</span>`;
        appLink.setAttribute('aria-label', `Open in ${service} app`);
        appLink.title = `Open in ${service} app`;
      }
      makeLink(url, 'Web', 'yhw-source-web');
    } else {
      makeLink(url, 'Open');
    }
  });
})();
</script>
{{/Source}}
<!-- /ankii source -->"""

SOURCE_CSS = """/* ankii source */
.yhw-source-card {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 18px;
  padding: 12px 14px;
  border: 1px solid rgba(127, 127, 127, 0.28);
  border-radius: 10px;
  background: rgba(127, 127, 127, 0.07);
  text-align: left;
}
.yhw-source-copy { flex: 1; min-width: 0; }
.yhw-source-label {
  margin-bottom: 3px;
  color: #888;
  font-size: 0.7em;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.yhw-source-title {
  overflow-wrap: anywhere;
  font-size: 0.9em;
  line-height: 1.35;
}
.yhw-source-link {
  flex: 0 0 auto;
  padding: 7px 12px;
  border-radius: 999px;
  background: #555;
  color: #fff !important;
  font-size: 0.78em;
  font-weight: 700;
  text-decoration: none;
}
.yhw-source-actions { display: flex; align-items: center; gap: 7px; }
.yhw-source-app { display: inline-flex; align-items: center; gap: 6px; padding-left: 7px; }
.yhw-source-app svg { display: block; width: 22px; height: 22px; }
.yhw-source-web { background: transparent; color: #555 !important; border: 1px solid #777; }
.nightMode .yhw-source-web { color: #ddd !important; border-color: #aaa; }
.yhw-source-raw { display: none; }
.nightMode .yhw-source-card { background: rgba(255, 255, 255, 0.06); }
.nightMode .yhw-source-label { color: #aaa; }
/* /ankii source */"""

EXAMPLE_CSS = """/* ankii examples */
.yhw-example {
  margin-top: 18px;
  padding: 14px 16px;
  border: 1px solid rgba(127, 127, 127, 0.35);
  border-radius: 10px;
  background: rgba(127, 127, 127, 0.06);
  text-align: left;
}
.yhw-example-target-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.yhw-example-vn {
  flex: 1;
  min-width: 0;
  font-size: 1.2em;
  line-height: 1.5;
}
.yhw-example-vn br, .yhw-example-en br {
  display: block;
  content: "";
  margin: 10px 0;
  border-top: 1px solid rgba(127, 127, 127, 0.28);
}
.yhw-target-audio {
  display: inline-flex;
  margin-left: 8px;
  vertical-align: middle;
}
.yhw-example-audio { flex: 0 0 auto; }
.yhw-target-audio .replay-button, .yhw-example-audio .replay-button {
  display: inline-flex;
  vertical-align: middle;
}
.yhw-target-audio .replay-button svg, .yhw-example-audio .replay-button svg {
  width: 22px;
  height: 22px;
}
.yhw-example-en {
  margin-top: 6px;
  color: #777;
  font-size: 0.95em;
  font-style: italic;
  line-height: 1.4;
}
.nightMode .yhw-example-en { color: #aaa; }
.nightMode .yhw-example { background: rgba(255, 255, 255, 0.05); }
/* /ankii examples */
""" + SOURCE_CSS

GRAMMAR_FIELDS = (
    "Grammar",
    "Explanation",
    "Example Target",
    "Example Native",
    "Source",
    "AIExplanation",
    "Import ID",
)

GRAMMAR_FRONT = """<div class="direction">Understand this grammar pattern</div>
<div class="grammar-pattern">{{Grammar}}</div>
{{#Example Target}}
<div class="example-prompt">{{Example Target}}</div>
{{/Example Target}}"""

GRAMMAR_BACK = """{{FrontSide}}
<div class="answer">
  <div class="grammar-explanation">{{Explanation}}</div>
</div>
{{#Example Native}}
<div class="source-translation">{{Example Native}}</div>
{{/Example Native}}
""" + SOURCE_TEMPLATE

GRAMMAR_CSS = """.card {
  box-sizing: border-box;
  max-width: 680px;
  margin: 0 auto;
  padding: 28px 22px;
  background: #faf8f3;
  color: #252525;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  text-align: center;
}
.direction {
  margin-bottom: 18px;
  color: #888;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.grammar-pattern {
  color: #b23a2b;
  font-size: 38px;
  font-weight: 750;
  line-height: 1.3;
}
.example-prompt {
  max-width: 560px;
  margin: 20px auto 0;
  padding: 16px 18px;
  background: #fff;
  border-left: 4px solid #d69b35;
  border-radius: 8px;
  font-size: 20px;
  line-height: 1.5;
  text-align: left;
}
.answer {
  margin-top: 26px;
  padding-top: 22px;
  border-top: 1px solid #d9d2c3;
}
.grammar-explanation {
  max-width: 580px;
  margin: 0 auto;
  font-size: 22px;
  line-height: 1.55;
  text-align: left;
}
.source-translation {
  max-width: 560px;
  margin: 10px auto 0;
  color: #666;
  font-size: 17px;
  font-style: italic;
  line-height: 1.45;
  text-align: left;
}
@media (max-width: 480px) {
  .card { padding: 22px 14px; }
  .grammar-pattern { font-size: 32px; }
}""" + SOURCE_CSS

VOCABULARY_FIELDS = (
    "Target",
    "Native",
    "Example Target",
    "Example Native",
    "Source",
    "Lesson",
    "AIExplanation",
    "Image",
    "Import ID",
    *VOCABULARY_AUDIO_FIELDS,
    RELATED_WORDS_FIELD,
)

VOCABULARY_FRONT = """{{#Image}}<div class="yhw-image">{{Image}}</div>{{/Image}}
<div class="yhw-target">{{Target}}</div>
"""

VOCABULARY_BACK = """{{FrontSide}}
<div class="yhw-answer">
  <div class="yhw-native">{{Native}}</div>
</div>
"""

VOCABULARY_CSS = """.card {
  box-sizing: border-box;
  max-width: 680px;
  margin: 0 auto;
  padding: 28px 22px;
  background: #faf8f3;
  color: #252525;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  text-align: center;
}
.yhw-image img {
  max-width: 100%;
  max-height: 320px;
  margin-bottom: 20px;
  border-radius: 10px;
}
.yhw-target {
  font-size: 38px;
  font-weight: 750;
  line-height: 1.3;
}
.yhw-answer {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #d9d2c3;
}
.yhw-native {
  font-size: 25px;
  line-height: 1.45;
}
@media (max-width: 480px) {
  .card { padding: 22px 14px; }
  .yhw-target { font-size: 32px; }
}
""" + EXAMPLE_CSS + RELATED_WORDS_CSS


def bootstrap_learning_models(
    vocabulary_model: str = "Vocabulary",
    grammar_model: str = "Grammar",
) -> dict[str, int]:
    """Create the managed learning models without requiring a legacy source model."""
    models = set(invoke("modelNames"))
    vocabulary_created = 0
    grammar_created = 0

    if vocabulary_model not in models:
        front = _place_target_audio(VOCABULARY_FRONT)
        back = _append_once(VOCABULARY_BACK, EXAMPLE_MARKERS[0], EXAMPLE_TEMPLATE)
        back = _append_once(back, SOURCE_MARKERS[0], SOURCE_TEMPLATE)
        back = _append_once(back, RELATED_WORDS_START, RELATED_WORDS_TEMPLATE)
        invoke(
            "createModel",
            modelName=vocabulary_model,
            inOrderFields=list(VOCABULARY_FIELDS),
            cardTemplates=[{"Name": "Vocabulary", "Front": front, "Back": back}],
            css=VOCABULARY_CSS,
        )
        vocabulary_created = 1

    if grammar_model not in models:
        invoke(
            "createModel",
            modelName=grammar_model,
            inOrderFields=list(GRAMMAR_FIELDS),
            cardTemplates=[
                {"Name": "Grammar", "Front": GRAMMAR_FRONT, "Back": GRAMMAR_BACK}
            ],
            css=GRAMMAR_CSS,
        )
        grammar_created = 1

    return {
        "vocabulary_created": vocabulary_created,
        "grammar_created": grammar_created,
    }


def _append_once(value: str, marker: str, addition: str) -> str:
    if marker in value:
        return value
    return f"{value.rstrip()}\n\n{addition}\n"


def _append_examples_if_missing(value: str, fields: tuple[str, ...], addition: str) -> str:
    if any(f"{{{{{field}}}}}" in value for field in fields):
        return value
    return _append_once(value, EXAMPLE_MARKERS[0], addition)


def _place_target_audio(value: str) -> str:
    """Place the managed replay button immediately after the rendered target field."""
    value = _remove_marked_block(value, *TARGET_AUDIO_MARKERS).rstrip()
    if "{{Target}}" not in value:
        return value
    return value.replace("{{Target}}", f"{{{{Target}}}}\n{TARGET_AUDIO_TEMPLATE}", 1)


def _place_example_audio(value: str) -> str:
    """Keep the replay control beside an existing example target field."""
    if all(marker in value for marker in INLINE_EXAMPLE_AUDIO_MARKERS):
        return value
    value = _remove_marked_block(value, *INLINE_EXAMPLE_AUDIO_MARKERS).rstrip()
    if "{{Example Audio}}" in value:
        return value
    target_field = next(
        (field for field in ("Example Target", "Example VN") if f"{{{{{field}}}}}" in value),
        None,
    )
    if target_field is None:
        return value
    reference = f"{{{{{target_field}}}}}"
    return value.replace(reference, f"{reference}\n{INLINE_EXAMPLE_AUDIO_TEMPLATE}", 1)


def _remove_marked_block(value: str, start: str, end: str) -> str:
    while start in value and end in value:
        before, remainder = value.split(start, 1)
        _removed, after = remainder.split(end, 1)
        value = f"{before.rstrip()}\n{after.lstrip()}"
    return value


def _close_unbalanced_css_blocks(value: str) -> str:
    """Close inherited CSS blocks before appending globally scoped managed styles."""
    missing = value.count("{") - value.count("}")
    if missing <= 0:
        return value
    return f"{value.rstrip()}\n" + "\n".join("}" for _ in range(missing))


def setup_learning_models(
    source_model: str = "Vietnamese",
    vocabulary_model: str = "Vocabulary",
    grammar_model: str = "Grammar",
) -> dict[str, int]:
    """Clone/migrate vocabulary notes and create the dedicated grammar model."""
    obsolete_template_blocks = (
        (
            "<!-- ankii everyday examples -->",
            "<!-- /ankii everyday examples -->",
        ),
        ("<!-- ankii examples -->", "<!-- /ankii examples -->"),
        (
            "<!-- yhw2anki everyday examples -->",
            "<!-- /yhw2anki everyday examples -->",
        ),
        LEGACY_EXAMPLE_MARKERS,
        SOURCE_MARKERS,
        LEGACY_SOURCE_MARKERS,
        (RELATED_WORDS_START, RELATED_WORDS_END),
        (VOCABULARY_LINK_START, VOCABULARY_LINK_END),
        LEGACY_VOCABULARY_LINK_MARKERS,
    )
    obsolete_css_blocks = (
        (
            "/* ankii everyday examples */",
            "/* /ankii everyday examples */",
        ),
        ("/* ankii examples */", "/* /ankii examples */"),
        (
            "/* yhw2anki everyday examples */",
            "/* /yhw2anki everyday examples */",
        ),
        LEGACY_EXAMPLE_CSS_MARKERS,
        SOURCE_CSS_MARKERS,
        LEGACY_SOURCE_CSS_MARKERS,
        (RELATED_WORDS_CSS_START, RELATED_WORDS_CSS_END),
        (VOCABULARY_LINK_CSS_START, VOCABULARY_LINK_CSS_END),
        LEGACY_VOCABULARY_LINK_CSS_MARKERS,
    )

    def clean_template(value: str) -> str:
        for start, end in obsolete_template_blocks:
            value = _remove_marked_block(value, start, end)
        value = _remove_marked_block(value, *TARGET_AUDIO_MARKERS)
        replacements = {
            "{{Vietnamese}}": "{{Target}}",
            "{{English}}": "{{Native}}",
            "{{Example VN}}": "{{Example Target}}",
            "{{Example EN}}": "{{Example Native}}",
            "{{Everyday Example VN}}": "{{Example Target}}",
            "{{Everyday Example EN}}": "{{Example Native}}",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value

    def clean_css(value: str) -> str:
        for start, end in obsolete_css_blocks:
            value = _remove_marked_block(value, start, end)
        return value

    models = list(invoke("modelNames"))
    vocabulary_created = 0
    if vocabulary_model not in models:
        if source_model not in models:
            raise ValueError(
                f"Anki has neither {source_model!r} nor {vocabulary_model!r}."
            )
        legacy_fields = invoke("modelFieldNames", modelName=source_model)
        renames = {
            "Vietnamese": "Target",
            "English": "Native",
            "Example VN": "Example Target",
            "Example EN": "Example Native",
        }
        fields = [
            renames.get(field, field)
            for field in legacy_fields
            if field not in {"Everyday Example VN", "Everyday Example EN"}
        ]
        if "Import ID" not in fields:
            fields.append("Import ID")
        for field in VOCABULARY_AUDIO_FIELDS:
            if field not in fields:
                fields.append(field)
        if RELATED_WORDS_FIELD not in fields:
            fields.append(RELATED_WORDS_FIELD)
        templates = invoke("modelTemplates", modelName=source_model)
        styling = invoke("modelStyling", modelName=source_model)
        cards = []
        for name, value in templates.items():
            back = _append_examples_if_missing(
                clean_template(value["Back"]), SOURCE_EXAMPLE_FIELDS, EXAMPLE_TEMPLATE
            )
            back = _place_example_audio(back)
            if "Source" in fields:
                back = _append_once(back, "<!-- ankii source -->", SOURCE_TEMPLATE)
            back = _append_once(back, RELATED_WORDS_START, RELATED_WORDS_TEMPLATE)
            front = _place_target_audio(clean_template(value["Front"]))
            back = _place_target_audio(back)
            cards.append({"Name": name, "Front": front, "Back": back})
        vocabulary_css = clean_css(str(styling.get("css", "")))
        vocabulary_css = _append_once(
            vocabulary_css, EXAMPLE_CSS_MARKERS[0], EXAMPLE_CSS
        )
        vocabulary_css = _append_once(
            vocabulary_css,
            RELATED_WORDS_CSS_START,
            RELATED_WORDS_CSS,
        )
        invoke(
            "createModel",
            modelName=vocabulary_model,
            inOrderFields=fields,
            cardTemplates=cards,
            css=vocabulary_css,
        )
        models.append(vocabulary_model)
        vocabulary_created = 1
    else:
        vocabulary_fields = invoke("modelFieldNames", modelName=vocabulary_model)
        legacy_vocabulary_fields = _migrate_generic_fields(
            vocabulary_model, vocabulary_fields
        )
        vocabulary_fields = invoke("modelFieldNames", modelName=vocabulary_model)
        for field in ("Import ID", *VOCABULARY_AUDIO_FIELDS, RELATED_WORDS_FIELD):
            if field not in vocabulary_fields:
                invoke("modelFieldAdd", modelName=vocabulary_model, fieldName=field)
                vocabulary_fields.append(field)
        templates = invoke("modelTemplates", modelName=vocabulary_model)
        cleaned_templates: dict[str, dict[str, str]] = {}
        for name, template in templates.items():
            cleaned = dict(template)
            for side in ("Front", "Back"):
                cleaned[side] = clean_template(cleaned[side])
            cleaned["Front"] = _place_target_audio(cleaned["Front"])
            cleaned["Back"] = _append_examples_if_missing(
                cleaned["Back"], SOURCE_EXAMPLE_FIELDS, EXAMPLE_TEMPLATE
            )
            cleaned["Back"] = _place_example_audio(cleaned["Back"])
            if "Source" in vocabulary_fields:
                cleaned["Back"] = _append_once(
                    cleaned["Back"], "<!-- ankii source -->", SOURCE_TEMPLATE
                )
            cleaned["Back"] = _append_once(
                cleaned["Back"], RELATED_WORDS_START, RELATED_WORDS_TEMPLATE
            )
            cleaned["Back"] = _place_target_audio(cleaned["Back"])
            cleaned_templates[name] = cleaned
        if cleaned_templates != templates:
            invoke(
                "updateModelTemplates",
                model={"name": vocabulary_model, "templates": cleaned_templates},
            )
        styling = invoke("modelStyling", modelName=vocabulary_model)
        css = str(styling.get("css", ""))
        cleaned_css = clean_css(css)
        cleaned_css = _append_once(cleaned_css, EXAMPLE_CSS_MARKERS[0], EXAMPLE_CSS)
        cleaned_css = _append_once(
            cleaned_css, RELATED_WORDS_CSS_START, RELATED_WORDS_CSS
        )
        if cleaned_css != css:
            invoke(
                "updateModelStyling",
                model={"name": vocabulary_model, "css": cleaned_css},
            )
        for field in legacy_vocabulary_fields:
            invoke("modelFieldRemove", modelName=vocabulary_model, fieldName=field)

    migrated = 0
    if source_model in models and source_model != vocabulary_model:
        note_ids = invoke("findNotes", query=f'note:"{source_model}"')
        notes = invoke("notesInfo", notes=note_ids) if note_ids else []
        for note in notes:
            migration_names = {
                "Vietnamese": "Target",
                "English": "Native",
                "Example VN": "Example Target",
                "Example EN": "Example Native",
            }
            fields = {
                migration_names.get(name, name): str(value.get("value", ""))
                for name, value in note.get("fields", {}).items()
                if isinstance(value, dict)
                and migration_names.get(name, name)
                not in {"Everyday Example VN", "Everyday Example EN"}
            }
            invoke(
                "updateNoteModel",
                note={
                    "id": note["noteId"],
                    "modelName": vocabulary_model,
                    "fields": fields,
                    "tags": list(note.get("tags", [])),
                },
            )
            migrated += 1

    grammar_created = 0
    if grammar_model not in models:
        invoke(
            "createModel",
            modelName=grammar_model,
            inOrderFields=list(GRAMMAR_FIELDS),
            cardTemplates=[
                {"Name": "Grammar", "Front": GRAMMAR_FRONT, "Back": GRAMMAR_BACK}
            ],
            css=GRAMMAR_CSS,
        )
        grammar_created = 1
    else:
        existing_fields = invoke("modelFieldNames", modelName=grammar_model)
        legacy_grammar_fields = _migrate_generic_fields(
            grammar_model, existing_fields, examples_only=True
        )
        existing_fields = invoke("modelFieldNames", modelName=grammar_model)
        for field in GRAMMAR_FIELDS:
            if field not in existing_fields:
                invoke("modelFieldAdd", modelName=grammar_model, fieldName=field)
        desired_template = {"Front": GRAMMAR_FRONT, "Back": GRAMMAR_BACK}
        existing_templates = invoke("modelTemplates", modelName=grammar_model)
        if existing_templates.get("Grammar") != desired_template:
            invoke(
                "updateModelTemplates",
                model={
                    "name": grammar_model,
                    "templates": {"Grammar": desired_template},
                },
            )
        existing_styling = invoke("modelStyling", modelName=grammar_model)
        if str(existing_styling.get("css", "")) != GRAMMAR_CSS:
            invoke(
                "updateModelStyling",
                model={"name": grammar_model, "css": GRAMMAR_CSS},
            )
        for field in legacy_grammar_fields:
            invoke("modelFieldRemove", modelName=grammar_model, fieldName=field)

    return {
        "vocabulary_created": vocabulary_created,
        "notes_migrated": migrated,
        "grammar_created": grammar_created,
    }


def _migrate_generic_fields(
    model: str, fields: list[str], *, examples_only: bool = False
) -> list[str]:
    """Migrate legacy fields and return redundant fields that can be removed."""
    pairs = [
        ("Example VN", "Example Target"),
        ("Example EN", "Example Native"),
        ("Everyday Example VN", "Example Target"),
        ("Everyday Example EN", "Example Native"),
    ]
    if not examples_only:
        pairs = [("Vietnamese", "Target"), ("English", "Native"), *pairs]
    removable: list[str] = []
    for old, new in pairs:
        if old not in fields:
            continue
        if new not in fields:
            invoke("modelFieldRename", modelName=model, oldFieldName=old, newFieldName=new)
            fields[fields.index(old)] = new
            continue
        note_ids = invoke("findNotes", query=f'note:"{model}"')
        notes = invoke("notesInfo", notes=note_ids) if note_ids else []
        for note in notes:
            old_value = str(note.get("fields", {}).get(old, {}).get("value", ""))
            new_value = str(note.get("fields", {}).get(new, {}).get("value", ""))
            if old_value and not new_value:
                invoke(
                    "updateNoteFields",
                    note={"id": note["noteId"], "fields": {new: old_value}},
                )
            elif old_value and old_value != new_value:
                if new in {"Example Target", "Example Native"}:
                    invoke(
                        "updateNoteFields",
                        note={
                            "id": note["noteId"],
                            "fields": {new: f"{new_value}<br>{old_value}"},
                        },
                    )
                else:
                    raise ValueError(
                        f"Cannot remove legacy field {old!r} from {model!r}: note "
                        f"{note['noteId']} has a different value in {new!r}."
                    )
        removable.append(old)
    return removable


def setup_note_type(model: str, *, apply_default_style: bool = False) -> dict[str, int]:
    """Add the example fields, migrate legacy values, and enhance card backs.

    Legacy fields are intentionally retained. Existing values are copied only when
    the corresponding new field is empty, so this operation is safe to repeat.
    """
    models = invoke("modelNames")
    if model not in models:
        available = ", ".join(repr(name) for name in models) or "none"
        raise ValueError(
            f"Anki note type {model!r} does not exist. Available note types: {available}."
        )

    original_fields = list(invoke("modelFieldNames", modelName=model))
    if apply_default_style:
        required = {"Target", "Native"}
        missing_required = sorted(required.difference(original_fields))
        if missing_required:
            raise ValueError(
                f"Cannot apply the default vocabulary style to {model!r}: missing required "
                f"fields {', '.join(missing_required)}. Run 'ankii anki setup-note-types' "
                "to migrate language-specific fields first."
            )
        managed_fields = VOCABULARY_FIELDS
    else:
        managed_fields = (*LEGACY_EXAMPLE_FIELDS, *VOCABULARY_AUDIO_FIELDS, "Import ID")
    for field in managed_fields:
        if field not in original_fields:
            invoke("modelFieldAdd", modelName=model, fieldName=field)

    migrated = 0
    legacy_sources = {
        "Example VN": ("ExampleVN", "Example", "Examples"),
        "Example EN": ("ExampleEN", "Example Translation"),
    }
    legacy_present = {
        target: [source for source in sources if source in original_fields]
        for target, sources in legacy_sources.items()
    }
    if any(legacy_present.values()):
        note_ids = invoke("findNotes", query=f'note:"{model}"')
        for note in invoke("notesInfo", notes=note_ids):
            fields = note.get("fields", {})
            updates: dict[str, str] = {}
            for target, sources in legacy_present.items():
                target_value = fields.get(target, {}).get("value", "")
                if target_value:
                    continue
                source_value = next(
                    (
                        fields[name].get("value", "")
                        for name in sources
                        if fields.get(name, {}).get("value")
                    ),
                    "",
                )
                if source_value:
                    updates[target] = source_value
            if updates:
                invoke("updateNoteFields", note={"id": note["noteId"], "fields": updates})
                migrated += 1

    templates: dict[str, dict[str, str]] = invoke("modelTemplates", modelName=model)
    changed_templates: dict[str, dict[str, str]] = {}
    for name, template in templates.items():
        updated = dict(template)
        if apply_default_style:
            updated["Front"] = _place_target_audio(VOCABULARY_FRONT)
            back = _append_once(VOCABULARY_BACK, EXAMPLE_MARKERS[0], EXAMPLE_TEMPLATE)
            back = _append_once(back, SOURCE_MARKERS[0], SOURCE_TEMPLATE)
            updated["Back"] = _append_once(
                back, RELATED_WORDS_START, RELATED_WORDS_TEMPLATE
            )
        else:
            updated["Front"] = _place_target_audio(template["Front"])
            back = template["Back"]
            for markers in (LEGACY_EXAMPLE_MARKERS, EXAMPLE_MARKERS):
                back = _remove_marked_block(back, *markers)
            updated["Back"] = _append_examples_if_missing(
                back, LEGACY_EXAMPLE_FIELDS, EXAMPLE_TEMPLATE
            )
            updated["Back"] = _place_example_audio(updated["Back"])
            updated["Back"] = _place_target_audio(updated["Back"])
            if "Source" in original_fields:
                for markers in (LEGACY_SOURCE_MARKERS, SOURCE_MARKERS):
                    updated["Back"] = _remove_marked_block(updated["Back"], *markers)
                updated["Back"] = _append_once(
                    updated["Back"], SOURCE_MARKERS[0], SOURCE_TEMPLATE
                )
        changed_templates[name] = updated
    if changed_templates != templates:
        invoke("updateModelTemplates", model={"name": model, "templates": changed_templates})

    styling: dict[str, Any] = invoke("modelStyling", modelName=model)
    css = str(styling.get("css", ""))
    if apply_default_style:
        updated_css = VOCABULARY_CSS
    else:
        updated_css = css
        for markers in (LEGACY_EXAMPLE_CSS_MARKERS, EXAMPLE_CSS_MARKERS):
            updated_css = _remove_marked_block(updated_css, *markers)
        for markers in (LEGACY_SOURCE_CSS_MARKERS, SOURCE_CSS_MARKERS):
            updated_css = _remove_marked_block(updated_css, *markers)
        updated_css = _close_unbalanced_css_blocks(updated_css)
        updated_css = _append_once(
            updated_css, EXAMPLE_CSS_MARKERS[0], EXAMPLE_CSS
        )
    if updated_css != css:
        invoke("updateModelStyling", model={"name": model, "css": updated_css})

    return {
        "fields_added": sum(field not in original_fields for field in managed_fields),
        "notes_migrated": migrated,
        "templates_updated": sum(
            template != changed_templates[name]
            for name, template in templates.items()
        ),
        "styling_updated": int(updated_css != css),
    }


def backfill_examples(review_path: Path, model: str) -> dict[str, int]:
    """Fill empty example fields on existing notes from a local review file."""
    review = load_review(review_path)
    fields = set(invoke("modelFieldNames", modelName=model))
    example_fields = (
        SOURCE_EXAMPLE_FIELDS
        if set(SOURCE_EXAMPLE_FIELDS) <= fields
        else ("Example VN", "Example EN")
    )
    missing = set(example_fields) - fields
    if missing:
        raise ValueError(
            f"Note type {model!r} is missing fields: {', '.join(sorted(missing))}. "
            "Run 'ankii anki setup-note-type' first."
        )

    source = str(review["lesson"].get("source_url", ""))
    cards_by_word: dict[str, dict[str, Any]] = {}
    ambiguous: set[str] = set()
    for card in review["cards"]:
        word = str(card.get("word", "")).strip()
        if word in cards_by_word:
            ambiguous.add(word)
        elif word:
            cards_by_word[word] = card

    note_ids = invoke("findNotes", query=f'note:"{model}"')
    matched = updated = 0
    for note in invoke("notesInfo", notes=note_ids):
        note_fields = note.get("fields", {})
        note_source = html.unescape(note_fields.get("Source", {}).get("value", "")).strip()
        word = html.unescape(
            note_fields.get("Target", note_fields.get("Vietnamese", {})).get("value", "")
        ).strip()
        if word in ambiguous or note_source != source or word not in cards_by_word:
            continue
        matched += 1
        card = cards_by_word[word]
        mappings = (
            (example_fields[0], "example_target"),
            (example_fields[1], "example_native"),
        )
        updates = {
            target: str(
                card.get(
                    key,
                    card.get("example_vn" if key == "example_target" else "example_en", ""),
                )
            )
            for target, key in mappings
            if target in fields
            if not note_fields.get(target, {}).get("value")
            and card.get(key, card.get("example_vn" if key == "example_target" else "example_en"))
        }
        if updates:
            invoke("updateNoteFields", note={"id": note["noteId"], "fields": updates})
            updated += 1

    return {
        "review_cards": len(cards_by_word),
        "notes_matched": matched,
        "notes_updated": updated,
        "ambiguous_words": len(ambiguous),
    }
