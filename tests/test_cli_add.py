from pathlib import Path

from ankii import cli
from ankii.review import load_review


def test_add_saves_approved_card(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "custom.json"
    answers = iter(["hello", "Xin chào.", "Hello.", "s"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(
        cli,
        "_choose_tags",
        lambda _card: (
            [
                "part_of_speech::expression",
                "topic::communication",
                "register::neutral",
                "level::A1",
            ],
            "A common greeting.",
        ),
    )
    monkeypatch.setattr(cli, "_choose_image", lambda _query: cli._empty_image())

    assert cli.run_add("xin chào", path) == 0

    saved = load_review(path)["cards"][0]
    assert saved["approved"] is True
    assert saved["example_vn"] == "Xin chào."
    assert "topic::communication" in saved["tags"]
    assert "card_type::vocabulary" in saved["tags"]


def test_add_cancel_does_not_create_inbox(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    answers = iter(["hello", "", "", "c"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(cli, "_choose_tags", lambda _card: (["level::A1"], ""))
    monkeypatch.setattr(cli, "_choose_image", lambda _query: cli._empty_image())

    assert cli.run_add("xin chào", path) == 0
    assert not path.exists()


def test_add_can_generate_bilingual_example(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "inbox.json"
    answers = iter(["hello", "ai", "s"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    monkeypatch.setattr(
        cli,
        "suggest_example_sentence",
        lambda word, meaning, model: ("Tôi nói xin chào.", "I say hello."),
    )
    monkeypatch.setattr(cli, "_choose_tags", lambda _card: (["level::A1"], ""))
    monkeypatch.setattr(cli, "_choose_image", lambda _query: cli._empty_image())

    assert cli.run_add("xin chào", path) == 0

    saved = load_review(path)["cards"][0]
    assert saved["example_vn"] == "Tôi nói xin chào."
    assert saved["example_en"] == "I say hello."
