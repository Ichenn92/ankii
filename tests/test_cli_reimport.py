from pathlib import Path

from ankii import cli


def test_reimport_arguments_are_optional() -> None:
    args = cli.build_parser().parse_args(["reimport"])

    assert args.reviews is None
    assert args.deck is None
    assert args.model is None


def test_reimport_prompts_for_reviews_deck_and_model(monkeypatch, tmp_path: Path) -> None:
    reviews = tmp_path / "reviews"
    reviews.mkdir()
    (reviews / "one.review.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "invoke",
        lambda action, **_kwargs: {
            "deckNames": ["Default", "Vietnamese"],
            "modelNames": ["Basic", "Vocabulary"],
        }[action],
    )
    answers = iter(["", "", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    selected = cli._resolve_reimport_options(None, None, None)

    assert selected == (Path("reviews"), "Vocabulary", "Vietnamese")


def test_reimport_keeps_explicit_values_without_prompt(monkeypatch) -> None:
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: (_ for _ in ()).throw(AssertionError("unexpected prompt")),
    )

    selected = cli._resolve_reimport_options(
        Path("custom-reviews"), "Custom Model", "Custom Deck"
    )

    assert selected == (Path("custom-reviews"), "Custom Model", "Custom Deck")
