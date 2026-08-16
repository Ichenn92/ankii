import io
from pathlib import Path

from ankii import cli
from ankii.analyzer import AnalysisCandidate, PassageAnalysis
from ankii.review import load_review


def _analysis() -> PassageAnalysis:
    tags = [
        "part_of_speech::expression",
        "topic::communication",
        "register::informal",
        "level::B1",
    ]
    candidates = [
        AnalysisCandidate(
            "đừng có mơ",
            "don't even dream of it",
            "Đừng có mơ.",
            "Don't even dream of it.",
            "Useful emphatic refusal.",
            tags,
            "vocabulary",
            "Đừng có mơ đến việc nghỉ sớm.",
            "Don't dream of leaving early.",
            "Đừng mơ nữa.",
            "Stop dreaming.",
        ),
        AnalysisCandidate(
            "tạm biệt",
            "goodbye",
            "Tạm biệt.",
            "Goodbye.",
            "A common farewell.",
            tags,
            "vocabulary",
            "Tôi nói tạm biệt đồng nghiệp.",
            "I say goodbye to my colleague.",
            "Tạm biệt nhé!",
            "Goodbye!",
        ),
    ]
    return PassageAnalysis(
        "Don't dream of it. Goodbye.",
        "A curt farewell.",
        ["informal"],
        "Everyday forceful speech.",
        [("đừng có", "An emphatic negative imperative.")],
        candidates,
    )


def test_read_analysis_text_from_argument_and_stdin(monkeypatch) -> None:
    assert cli._read_analysis_text("  Xin chào. ") == "Xin chào."
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("Tạm biệt.\n"))
    assert cli._read_analysis_text(None) == "Tạm biệt."


def test_run_analyze_saves_default_unknown_candidates(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    monkeypatch.setattr(cli, "analyze_passage", lambda _text, _model: _analysis())
    monkeypatch.setattr(cli, "known_anki_headwords", lambda: ({"đừng có mơ"}, "Vietnamese"))
    answers = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    result = cli.run_analyze("Đừng có mơ. Tạm biệt.", "A song", "https://song", path, "m")

    assert result == 0
    cards = load_review(path)["cards"]
    assert [card["word"] for card in cards] == ["tạm biệt"]
    assert cards[0]["source_title"] == "A song"
    assert cards[0]["source_url"] == "https://song"
    assert cards[0]["approved"] is True
    assert "source::analysis" in cards[0]["tags"]


def test_run_analyze_cancel_does_not_create_inbox(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    monkeypatch.setattr(cli, "analyze_passage", lambda _text, _model: _analysis())
    monkeypatch.setattr(cli, "known_anki_headwords", lambda: (set(), None))
    monkeypatch.setattr("builtins.input", lambda _prompt: "q")

    assert cli.run_analyze("Đừng có mơ. Tạm biệt.", "", "", path, "m") == 0
    assert not path.exists()


def test_run_analyze_saves_grammar_card_for_vietnamese_model(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    grammar = AnalysisCandidate(
        "có … thì …",
        "Creates a conditional meaning, often with emphasis.",
        "Anh có thương thì qua.",
        "If you do care for me, then come over.",
        "A reusable conditional frame.",
        [
            "part_of_speech::other",
            "topic::communication",
            "register::neutral",
            "level::B1",
        ],
        "grammar",
        "Có thời gian thì gọi cho tôi nhé.",
        "If you have time, give me a call.",
        "Có đói thì ăn nhé.",
        "If you are hungry, eat.",
    )
    analysis = PassageAnalysis(
        "If you care for me, come over.",
        "A conditional invitation.",
        ["poetic"],
        "A lyrical conditional construction.",
        [("có … thì …", "Creates an emphatic conditional.")],
        [grammar],
    )
    monkeypatch.setattr(cli, "analyze_passage", lambda _text, _model: analysis)
    monkeypatch.setattr(cli, "known_anki_headwords", lambda: (set(), "Vietnamese"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")

    assert cli.run_analyze("Anh có thương thì qua.", "", "", path, "m") == 0

    card = load_review(path)["cards"][0]
    assert card["word"] == "có … thì …"
    assert card["meaning"].startswith("Creates a conditional")
    assert "card_type::grammar" in card["tags"]
    assert card["example_vn"] == (
        "Anh có thương thì qua.\nCó thời gian thì gọi cho tôi nhé.\nCó đói thì ăn nhé."
    )
    assert card["example_en"] == (
        "If you do care for me, then come over.\nIf you have time, give me a call.\n"
        "If you are hungry, eat."
    )


def test_display_analysis_shows_suggestion_position_and_level(capsys) -> None:
    candidate = _analysis().candidates[0]
    cli._display_analysis_candidate(candidate, 1, 2, set(), set())

    output = capsys.readouterr().out
    assert "[1/2] [vocabulary · B1] đừng có mơ" in output


def test_resolve_analysis_sources_prompts_with_empty_defaults(monkeypatch) -> None:
    monkeypatch.setattr(cli.sys, "stdin", type("TTY", (), {"isatty": lambda self: True})())
    answers = iter(["A song", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert cli._resolve_analysis_sources(None, None) == ("A song", "")
