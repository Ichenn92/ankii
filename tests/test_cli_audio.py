from pathlib import Path
from unittest.mock import patch

from ankii import cli
from ankii.audio import MissingAudio, load_audio_skips
from ankii.settings import AudioSettings, LanguageProfile


def _profile(tmp_path: Path) -> LanguageProfile:
    return LanguageProfile(
        "vietnamese",
        "Vietnamese",
        "English",
        "Vietnamese",
        "A1",
        "B2",
        review_base=tmp_path / "reviews",
        audio=AudioSettings(enabled=True, accent="Southern Vietnamese"),
    )


def test_backfill_audio_parser_uses_configured_model_by_default() -> None:
    args = cli.build_parser().parse_args(["backfill-audio"])

    assert args.model is None


def test_audio_backfill_generates_yes_and_persists_no(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    candidates = [
        MissingAudio(1, "xin chào", "xin chào", "target", "Target Audio", "one.mp3", ""),
        MissingAudio(
            1,
            "xin chào",
            "Xin chào bạn.",
            "example",
            "Example Audio",
            "two.mp3",
            "",
        ),
    ]
    answers = iter(["y", "n"])

    with (
        patch("ankii.cli.missing_audio", return_value=(candidates, 0)),
        patch("ankii.cli.create_speech_client", return_value=object()),
        patch(
            "ankii.cli.install_missing_audio", return_value=("[sound:one.mp3]", True)
        ) as install,
        patch("builtins.input", side_effect=lambda _prompt: next(answers)),
    ):
        assert cli.run_audio_backfill("Vocabulary", profile) == 0

    install.assert_called_once()
    skipped = load_audio_skips(profile.audio_skip_path)
    assert set(skipped) == {"two.mp3"}
    assert skipped["two.mp3"]["text"] == "Xin chào bạn."


def test_audio_backfill_all_no_never_requires_api_client(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    candidate = MissingAudio(
        1, "xin chào", "xin chào", "target", "Target Audio", "one.mp3", ""
    )

    with (
        patch("ankii.cli.missing_audio", return_value=([candidate], 0)),
        patch("ankii.cli.create_speech_client") as client,
        patch("builtins.input", return_value="no"),
    ):
        assert cli.run_audio_backfill("Vocabulary", profile) == 0

    client.assert_not_called()
    assert "one.mp3" in load_audio_skips(profile.audio_skip_path)
