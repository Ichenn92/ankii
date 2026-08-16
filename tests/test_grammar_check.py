import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ankii import grammar_check
from ankii.grammar_check import (
    GrammarSuggestion,
    example_lines,
    load_ignored,
    normalize_pattern,
    save_ignored,
    vocabulary_inputs,
)

TAGS = [
    "part_of_speech::other",
    "topic::communication",
    "register::neutral",
    "level::B1",
]


def _note() -> dict:
    return {
        "noteId": 12,
        "fields": {
            "Vietnamese": {"value": "thương"},
            "Example VN": {"value": "Anh có thương thì qua.<br>Có thời gian thì gọi tôi."},
            "Example EN": {"value": "If you care, come over.<br>If you have time, call me."},
            "Source": {"value": "A song"},
        },
    }


def _suggestion(pattern: str = "có … thì …") -> GrammarSuggestion:
    return GrammarSuggestion(
        pattern=pattern,
        explanation="Creates a conditional meaning.",
        example_vn="Anh có thương thì qua.",
        example_en="If you care, come over.",
        everyday_example_vn="Có việc gì thì gọi cho tôi nhé.",
        everyday_example_en="If anything comes up, call me.",
        tags=TAGS,
        source_note_id=12,
        source_word="thương",
        source="A song",
    )


def test_example_lines_reads_html_multiline() -> None:
    assert example_lines("Một câu.<br> Câu hai.<div>Câu ba.</div>") == [
        "Một câu.",
        "Câu hai.Câu ba.",
    ]


def test_vocabulary_inputs_pairs_examples_and_skips_empty(monkeypatch) -> None:
    empty = {"noteId": 13, "fields": {"Vietnamese": {"value": "trống"}}}
    monkeypatch.setattr(grammar_check, "notes_for_model", lambda _model: [_note(), empty])

    inputs, skipped = vocabulary_inputs("Vocabulary")

    assert skipped == 1
    assert inputs[0]["examples"][1] == {
        "vietnamese": "Có thời gian thì gọi tôi.",
        "english": "If you have time, call me.",
    }


def test_suggest_batch_validates_and_returns_source(monkeypatch) -> None:
    parsed = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                pattern="có … thì …",
                explanation="Creates a conditional meaning.",
                example_vn="Anh có thương thì qua.",
                example_en="If you care, come over.",
                everyday_example_vn="Có việc gì thì gọi cho tôi nhé.",
                everyday_example_en="If anything comes up, call me.",
                tags=TAGS,
                source_note_id=12,
            )
        ]
    )

    class FakeResponses:
        def parse(self, **kwargs):
            assert kwargs["store"] is False
            return SimpleNamespace(output_parsed=parsed)

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    batch, _skipped = vocabulary_inputs_from_note(monkeypatch)

    result = grammar_check._suggest_batch(batch, set(), "test-model")

    assert result == [_suggestion()]


def vocabulary_inputs_from_note(monkeypatch):
    monkeypatch.setattr(grammar_check, "notes_for_model", lambda _model: [_note()])
    return vocabulary_inputs("Vocabulary")


def test_suggest_batch_rejects_changed_source_translation(monkeypatch) -> None:
    candidate = SimpleNamespace(
        pattern="có … thì …",
        explanation="Conditional.",
        example_vn="Anh có thương thì qua.",
        example_en="A changed translation.",
        everyday_example_vn="Có việc thì gọi tôi.",
        everyday_example_en="If needed, call me.",
        tags=TAGS,
        source_note_id=12,
    )

    class FakeOpenAI:
        def __init__(self, api_key):
            self.responses = SimpleNamespace(
                parse=lambda **_kwargs: SimpleNamespace(
                    output_parsed=SimpleNamespace(candidates=[candidate])
                )
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    batch, _skipped = vocabulary_inputs_from_note(monkeypatch)

    with pytest.raises(RuntimeError, match="changed"):
        grammar_check._suggest_batch(batch, set(), "test-model")


def test_ignore_file_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "ignore.json"
    patterns = {normalize_pattern("Có … thì …"): {"pattern": "có … thì …"}}

    save_ignored(path, patterns)

    assert load_ignored(path) == patterns
    assert json.loads(path.read_text())["ignore_version"] == 1


def test_discover_grammar_deduplicates_across_batches(monkeypatch) -> None:
    monkeypatch.setattr(grammar_check, "BATCH_SIZE", 1)
    monkeypatch.setattr(
        grammar_check,
        "vocabulary_inputs",
        lambda _model: ([{"note_id": 1}, {"note_id": 2}], 0),
    )
    monkeypatch.setattr(grammar_check, "grammar_patterns", lambda _model: {"đã có"})
    calls = []

    def fake_batch(_batch, known, _model):
        calls.append(set(known))
        return [_suggestion()] if len(calls) == 1 else []

    monkeypatch.setattr(grammar_check, "_suggest_batch", fake_batch)

    result, stats = grammar_check.discover_grammar("Vocabulary", "Grammar", "m", set())

    assert result == [_suggestion()]
    assert normalize_pattern("có … thì …") in calls[1]
    assert stats["suggestions"] == 1
