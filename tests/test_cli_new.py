import io
from pathlib import Path

import pytest

from ankii import cli
from ankii.review import load_review
from ankii.settings import LanguageProfile


def _profile(tmp_path: Path) -> LanguageProfile:
    return LanguageProfile(
        name="french",
        study_language="French",
        native_language="English",
        deck="French",
        analysis_min_level="A1",
        analysis_max_level="B2",
        review_base=tmp_path,
    )


def test_word_list_entries_accepts_plain_bulleted_numbered_and_mixed_lines() -> None:
    assert cli._word_list_entries("bonjour\n- goodbye\n3. merci = thank you\n\n") == [
        "bonjour",
        "goodbye",
        "merci = thank you",
    ]


def test_read_word_list_uses_piped_stdin(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("bonjour\ngoodbye\n"))
    assert cli._read_word_list(None) == ["bonjour", "goodbye"]


def test_run_new_creates_unapproved_review(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "class.txt"
    source.write_text("bonjour\ngoodbye\n", encoding="utf-8")
    output = tmp_path / "class.review.json"
    profile = _profile(tmp_path)

    def fake_generate(entries, title, model, selected_profile):
        assert entries == ["bonjour", "goodbye"]
        assert (title, model, selected_profile) == ("Class 1", "model", profile)
        return {
            "review_version": 2,
            "review_kind": "generated_word_list",
            "lesson": {
                "public_id": "word-list",
                "title": title,
                "source_language": "French",
                "source_url": "",
            },
            "profile": {
                "name": "french",
                "study_language": "French",
                "native_language": "English",
            },
            "cards": [
                {
                    "word": "bonjour",
                    "meaning": "hello",
                    "example_target": "Bonjour !",
                    "example_native": "Hello!",
                    "tags": [],
                    "approved": False,
                    "skip": False,
                }
            ],
        }

    monkeypatch.setattr(cli, "generate_word_list_review", fake_generate)
    assert cli.run_new(source, output, "Class 1", "model", profile) == 0
    assert load_review(output)["cards"][0]["approved"] is False


def test_run_new_refuses_to_overwrite(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "words.txt"
    source.write_text("bonjour\n", encoding="utf-8")
    output = tmp_path / "existing.json"
    output.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="Output already exists"):
        cli.run_new(source, output, None, "model", _profile(tmp_path))


def test_parser_accepts_new_options() -> None:
    args = cli.build_parser().parse_args(
        ["new", "words.txt", "--output", "result.json", "--title", "Class"]
    )
    assert args.command == "new"
    assert args.input_file == Path("words.txt")
    assert args.output == Path("result.json")
