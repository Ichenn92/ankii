from pathlib import Path

import pytest

from ankii.audio import (
    LocalSpeechClient,
    LocalVoice,
    MissingAudio,
    add_audio_skip,
    attach_audio,
    audio_filename,
    create_speech_client,
    example_audio_lines,
    example_audio_text,
    install_missing_audio,
    load_audio_skips,
    local_voices,
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


def _local_profile(tmp_path: Path) -> LanguageProfile:
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
            provider="local",
            model="macos-say",
            voice="Linh",
            language="vi_VN",
        ),
    )


def test_example_audio_lines_supports_plain_and_html_breaks() -> None:
    assert example_audio_lines(" Một câu. <br>Câu hai.<div>Câu ba.</div> ") == [
        "Một câu.",
        "Câu hai.",
        "Câu ba.",
    ]
    assert example_audio_text("Một câu.<br>Câu hai.") == "Một câu.\nCâu hai."


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

    assert first.generated == 2
    assert first.cached == 0
    assert not first.failures
    assert [item["fields"] for item in note["audio"]] == [
        ["Target Audio"],
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
    assert client.audio.speech.calls[1]["input"] == "Xin chào bạn.\nChào buổi sáng."
    assert second.cached == 2
    assert len(client.audio.speech.calls) == 2


def test_attach_audio_retries_and_keeps_partial_success(
    monkeypatch, tmp_path: Path
) -> None:
    profile = _profile(tmp_path)
    combined = "Câu được.\nCâu lỗi."
    client = FakeClient({"xin chào": 1, combined: 3})
    monkeypatch.setattr("ankii.audio.time.sleep", lambda _seconds: None)
    note = {"modelName": "Vocabulary", "fields": {}}
    card = {"word": "xin chào", "example_target": "Câu được.\nCâu lỗi."}

    result = attach_audio(
        [(note, card)],
        profile,
        {"target_audio": "Target Audio", "example_audio": "Example Audio"},
        client,
    )

    assert result.generated == 1
    assert result.cached == 0
    assert [failure.text for failure in result.failures] == [combined]
    assert [call["input"] for call in client.audio.speech.calls].count("xin chào") == 2
    assert [call["input"] for call in client.audio.speech.calls].count(combined) == 3
    assert len(note["audio"]) == 1


def test_speech_client_requires_existing_openai_credentials(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("ankii.audio.get_openai_api_key", lambda: (None, None))

    with pytest.raises(RuntimeError, match="no OpenAI API key"):
        create_speech_client(_profile(tmp_path))


def test_local_voices_lists_and_filters_installed_macos_voices(monkeypatch) -> None:
    output = "Linh                vi_VN    # Xin chào!\nAmélie              fr_CA    # Bonjour!\n"
    monkeypatch.setattr("ankii.audio.sys.platform", "darwin")
    monkeypatch.setattr("ankii.audio.shutil.which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        "ankii.audio.subprocess.run",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": output})(),
    )

    assert local_voices("Vietnamese") == [LocalVoice("Linh", "vi_VN")]
    assert len(local_voices()) == 2


def test_local_generation_uses_say_and_ffmpeg_without_openai(monkeypatch, tmp_path: Path) -> None:
    profile = _local_profile(tmp_path)
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs):
        calls.append(command)
        output = Path(command[command.index("-o") + 1]) if "-o" in command else Path(command[-1])
        output.write_bytes(b"local audio")
        return type("Result", (), {"stdout": "", "stderr": b""})()

    monkeypatch.setattr("ankii.audio.subprocess.run", run)
    note = {"modelName": "Vocabulary", "fields": {}}
    result = attach_audio(
        [(note, {"word": "xin chào", "example_target": ""})],
        profile,
        {"target_audio": "Target Audio", "example_audio": "Example Audio"},
        LocalSpeechClient("/usr/bin/say", "/opt/homebrew/bin/ffmpeg"),
    )

    assert result.generated == 1
    assert calls[0][:4] == ["/usr/bin/say", "-v", "Linh", "-o"]
    assert calls[1][0] == "/opt/homebrew/bin/ffmpeg"
    assert calls[1][calls[1].index("-f") + 1] == "mp3"
    assert Path(note["audio"][0]["path"]).read_bytes() == b"local audio"


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


def test_missing_audio_accepts_existing_clips_from_another_configuration(
    monkeypatch, tmp_path: Path
) -> None:
    profile = _profile(tmp_path)
    target_filename = audio_filename(profile, "xin chào")
    combined_example = audio_filename(profile, "Xin chào bạn.\nChào buổi sáng.")
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
                    "Example Audio": {"value": "[sound:old-first-example.mp3]"},
                },
            }
        ],
    )

    candidates, ignored = missing_audio("Vocabulary", profile, {combined_example})

    assert candidates == []
    assert ignored == 0

    candidates, ignored = missing_audio("Vocabulary", profile)
    assert ignored == 0
    assert candidates == []


def test_missing_audio_still_offers_empty_fields(monkeypatch, tmp_path: Path) -> None:
    profile = _profile(tmp_path)
    fields = ["Target", "Example Target", "Target Audio", "Example Audio"]
    monkeypatch.setattr(
        "ankii.audio.invoke",
        lambda action, **_kwargs: fields if action == "modelFieldNames" else None,
    )
    monkeypatch.setattr(
        "ankii.audio.notes_for_model",
        lambda _model, _deck: [
            {
                "noteId": 10,
                "fields": {
                    "Target": {"value": "xin chào"},
                    "Example Target": {"value": "Xin chào bạn.<br>Chào buổi sáng."},
                    "Target Audio": {"value": ""},
                    "Example Audio": {"value": ""},
                },
            }
        ],
    )

    candidates, ignored = missing_audio("Vocabulary", profile)

    assert ignored == 0
    assert [(item.text, item.kind) for item in candidates] == [
        ("xin chào", "target"),
        ("Xin chào bạn.\nChào buổi sáng.", "example"),
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
    assert updated == f"[sound:{filename}]"
    assert calls[-1] == (
        "updateNoteFields",
        {"note": {"id": 10, "fields": {"Example Audio": updated}}},
    )
