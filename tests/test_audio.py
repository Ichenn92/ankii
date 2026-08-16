from pathlib import Path

import pytest

from ankii.audio import (
    MissingAudio,
    add_audio_skip,
    attach_audio,
    audio_filename,
    create_speech_client,
    example_audio_lines,
    install_missing_audio,
    load_audio_skips,
    missing_audio,
    save_audio_skips,
    speech_instructions,
)
from ankii.settings import AudioSettings, LanguageProfile


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def stream_to_file(self, path: Path) -> None:
        path.write_bytes(b"mp3 data")


class FakeTransientError(RuntimeError):
    status_code = 429


class FakeSpeech:
    def __init__(self, failures: dict[str, int] | None = None) -> None:
        self.with_streaming_response = self
        self.calls: list[dict[str, str]] = []
        self.failures = failures or {}

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = kwargs["input"]
        if self.failures.get(text, 0):
            self.failures[text] -= 1
            raise FakeTransientError("temporary TTS failure")
        return FakeResponse()


class FakeClient:
    def __init__(self, failures: dict[str, int] | None = None) -> None:
        self.audio = type("Audio", (), {})()
        self.audio.speech = FakeSpeech(failures)


def _profile(tmp_path: Path) -> LanguageProfile:
    return LanguageProfile(
        "vietnamese",
        "Vietnamese",
        "English",
        "Vietnamese",
        "A1",
        "B2",
        review_base=tmp_path / "reviews",
        audio=AudioSettings(
            enabled=True,
            provider="openai",
            model="gpt-4o-mini-tts",
            voice="marin",
            accent="Southern Vietnamese (Saigon)",
            instructions="Speak clearly at a learner-friendly pace.",
        ),
    )


def test_example_audio_lines_supports_plain_and_html_breaks() -> None:
    assert example_audio_lines(" Một câu. <br>Câu hai.<div>Câu ba.</div> ") == [
        "Một câu.",
        "Câu hai.",
        "Câu ba.",
    ]


def test_instructions_and_filename_include_profile_configuration(tmp_path: Path) -> None:
    profile = _profile(tmp_path)

    assert speech_instructions(profile) == (
        "Speak Vietnamese naturally and accurately. "
        "Use a natural Southern Vietnamese (Saigon) accent. "
        "Speak clearly at a learner-friendly pace."
    )
    assert audio_filename(profile, " xin   chào ") == audio_filename(profile, "xin chào")

    other = LanguageProfile(
        **{**profile.__dict__, "audio": AudioSettings(enabled=True, accent="Northern Vietnamese")}
    )
    assert audio_filename(profile, "xin chào") != audio_filename(other, "xin chào")


def test_attach_audio_generates_and_then_reuses_cached_clips(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    client = FakeClient()
    note = {"modelName": "Vocabulary", "fields": {}}
    card = {
        "word": "xin chào",
        "example_target": "Xin chào bạn.\nChào buổi sáng.",
    }
    fields = {"target_audio": "Target Audio", "example_audio": "Example Audio"}

    first = attach_audio([(note, card)], profile, fields, client)

    assert first.generated == 3
    assert first.cached == 0
    assert not first.failures
    assert [item["fields"] for item in note["audio"]] == [
        ["Target Audio"],
        ["Example Audio"],
        ["Example Audio"],
    ]
    assert client.audio.speech.calls[0] == {
        "model": "gpt-4o-mini-tts",
        "voice": "marin",
        "input": "xin chào",
        "instructions": speech_instructions(profile),
        "response_format": "mp3",
    }
    assert all(Path(item["path"]).is_file() for item in note["audio"])
    assert not list(profile.audio_cache_path.glob("*.tmp"))

    second_note = {"modelName": "Vocabulary", "fields": {}}
    second = attach_audio([(second_note, card)], profile, fields, client)

    assert second.generated == 0
    assert second.cached == 3
    assert len(client.audio.speech.calls) == 3


def test_attach_audio_retries_and_keeps_partial_success(
    monkeypatch, tmp_path: Path
) -> None:
    profile = _profile(tmp_path)
    client = FakeClient({"xin chào": 1, "Câu lỗi.": 3})
    monkeypatch.setattr("ankii.audio.time.sleep", lambda _seconds: None)
    note = {"modelName": "Vocabulary", "fields": {}}
    card = {"word": "xin chào", "example_target": "Câu được.\nCâu lỗi."}

    result = attach_audio(
        [(note, card)],
        profile,
        {"target_audio": "Target Audio", "example_audio": "Example Audio"},
        client,
    )

    assert result.generated == 2
    assert result.cached == 0
    assert [failure.text for failure in result.failures] == ["Câu lỗi."]
    assert [call["input"] for call in client.audio.speech.calls].count("xin chào") == 2
    assert [call["input"] for call in client.audio.speech.calls].count("Câu lỗi.") == 3
    assert len(note["audio"]) == 2


def test_speech_client_requires_existing_openai_credentials(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ankii.audio.get_openai_api_key", lambda: (None, None))

    with pytest.raises(RuntimeError, match="no OpenAI API key"):
        create_speech_client(_profile(tmp_path))


def test_audio_skips_round_trip_with_generation_configuration(tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    candidate = MissingAudio(
        10,
        "xin chào",
        "Xin chào bạn.",
        "example",
        "Example Audio",
        audio_filename(profile, "Xin chào bạn."),
        "",
    )
    path = profile.audio_skip_path

    save_audio_skips(path, add_audio_skip({}, candidate, profile))

    saved = load_audio_skips(path)[candidate.filename]
    assert saved["text"] == "Xin chào bạn."
    assert saved["voice"] == "marin"
    assert saved["accent"] == "Southern Vietnamese (Saigon)"
    assert saved["skipped_at"]


def test_missing_audio_finds_only_uninstalled_and_unignored_clips(
    monkeypatch, tmp_path: Path
) -> None:
    profile = _profile(tmp_path)
    target_filename = audio_filename(profile, "xin chào")
    first_example = audio_filename(profile, "Xin chào bạn.")
    second_example = audio_filename(profile, "Chào buổi sáng.")
    fields = [
        "Target",
        "Example Target",
        "Target Audio",
        "Example Audio",
    ]
    monkeypatch.setattr(
        "ankii.audio.invoke",
        lambda action, **_kwargs: fields if action == "modelFieldNames" else None,
    )
    monkeypatch.setattr(
        "ankii.audio.notes_for_model",
        lambda model, deck: [
            {
                "noteId": 10,
                "fields": {
                    "Target": {"value": "xin chào"},
                    "Example Target": {"value": "Xin chào bạn.<br>Chào buổi sáng."},
                    "Target Audio": {"value": f"[sound:{target_filename}]"},
                    "Example Audio": {"value": f"[sound:{first_example}]"},
                },
            }
        ],
    )

    candidates, ignored = missing_audio("Vocabulary", profile, {second_example})

    assert candidates == []
    assert ignored == 1

    candidates, ignored = missing_audio("Vocabulary", profile)
    assert ignored == 0
    assert [(item.text, item.kind) for item in candidates] == [
        ("Chào buổi sáng.", "example")
    ]


def test_install_missing_audio_appends_sound_and_updates_note(monkeypatch, tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    text = "Xin chào bạn."
    filename = audio_filename(profile, text)
    profile.audio_cache_path.mkdir(parents=True)
    (profile.audio_cache_path / filename).write_bytes(b"cached mp3")
    candidate = MissingAudio(
        10,
        "xin chào",
        text,
        "example",
        "Example Audio",
        filename,
        "[sound:old.mp3]",
    )
    calls = []

    def fake_invoke(action, **kwargs):
        calls.append((action, kwargs))
        return filename if action == "storeMediaFile" else None

    monkeypatch.setattr("ankii.audio.invoke", fake_invoke)

    updated, generated = install_missing_audio(
        candidate, profile, FakeClient(), candidate.existing_value
    )

    assert generated is False
    assert updated == f"[sound:old.mp3] [sound:{filename}]"
    assert calls[-1] == (
        "updateNoteFields",
        {"note": {"id": 10, "fields": {"Example Audio": updated}}},
    )
