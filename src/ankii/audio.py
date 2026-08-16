from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ankii.anki import invoke
from ankii.importer import infer_field_names
from ankii.keychain import get_openai_api_key
from ankii.maintenance import notes_for_model
from ankii.settings import AudioSettings, LanguageProfile

AUDIO_SKIP_VERSION = 1
AUDIO_REFERENCE_RE = re.compile(r"(?i)\[sound:[^\]]+\]")
LANGUAGE_PREFIXES = {
    "Arabic": "ar",
    "Cantonese": "yue",
    "Catalan": "ca",
    "Czech": "cs",
    "Danish": "da",
    "Dutch": "nl",
    "English": "en",
    "Finnish": "fi",
    "French": "fr",
    "German": "de",
    "Greek": "el",
    "Hebrew": "he",
    "Hindi": "hi",
    "Hungarian": "hu",
    "Indonesian": "id",
    "Italian": "it",
    "Japanese": "ja",
    "Korean": "ko",
    "Malay": "ms",
    "Mandarin Chinese": "zh",
    "Norwegian": "nb",
    "Persian": "fa",
    "Polish": "pl",
    "Portuguese": "pt",
    "Romanian": "ro",
    "Russian": "ru",
    "Spanish": "es",
    "Swedish": "sv",
    "Thai": "th",
    "Turkish": "tr",
    "Ukrainian": "uk",
    "Vietnamese": "vi",
}


@dataclass(frozen=True)
class AudioFailure:
    text: str
    error: str


@dataclass(frozen=True)
class AudioGenerationResult:
    generated: int
    cached: int
    failures: tuple[AudioFailure, ...]


@dataclass(frozen=True)
class MissingAudio:
    note_id: int
    word: str
    text: str
    kind: str
    field: str
    filename: str
    existing_value: str


@dataclass(frozen=True)
class LocalVoice:
    name: str
    language: str


@dataclass(frozen=True)
class LocalSpeechClient:
    say: str
    ffmpeg: str


def audio_enabled(profile: LanguageProfile) -> bool:
    return profile.audio is not None and profile.audio.enabled


def example_audio_lines(value: object) -> list[str]:
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<(?:div|p|li)(?:\s[^>]*)?>", "\n", text)
    text = re.sub(r"(?i)</(?:div|p|li)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return [
        re.sub(r"\s+", " ", html.unescape(line)).strip()
        for line in text.splitlines()
        if line.strip()
    ]


def example_audio_text(value: object) -> str:
    """Combine every displayed example line into one speech input and one clip."""
    return "\n".join(example_audio_lines(value))


def speech_instructions(profile: LanguageProfile) -> str:
    settings = _enabled_settings(profile)
    parts = [f"Speak {profile.study_language} naturally and accurately."]
    if settings.accent:
        parts.append(f"Use a natural {settings.accent} accent.")
    if settings.instructions:
        parts.append(settings.instructions)
    return " ".join(parts)


def audio_filename(profile: LanguageProfile, text: str) -> str:
    settings = _enabled_settings(profile)
    normalized = re.sub(r"\s+", " ", html.unescape(text)).strip()
    identity = json.dumps(
        {
            "provider": settings.provider,
            "model": settings.model,
            "voice": settings.voice,
            "language": profile.study_language,
            "speech_language": settings.language,
            "accent": settings.accent,
            "instructions": settings.instructions,
            "text": normalized,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"ankii-tts-{digest}.mp3"


def create_speech_client(profile: LanguageProfile) -> Any:
    settings = _enabled_settings(profile)
    if settings.provider == "local":
        if sys.platform != "darwin":
            raise RuntimeError("Local audio generation currently requires macOS.")
        say = shutil.which("say")
        ffmpeg = shutil.which("ffmpeg")
        if not say or not ffmpeg:
            raise RuntimeError(
                "Local audio generation requires the macOS 'say' command and ffmpeg."
            )
        voices = local_voices()
        selected = next((item for item in voices if item.name == settings.voice), None)
        if selected is None:
            raise RuntimeError(
                f"Local voice {settings.voice!r} is not installed. Run 'ankii audio voices'."
            )
        if settings.language and selected.language.casefold() != settings.language.casefold():
            raise RuntimeError(
                f"Local voice {settings.voice!r} uses {selected.language}, not "
                f"{settings.language}. Run 'ankii audio voices'."
            )
        return LocalSpeechClient(say, ffmpeg)
    if settings.provider != "openai":
        raise RuntimeError(f"Unsupported audio provider: {settings.provider!r}.")
    api_key, _source = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "Audio generation is enabled but no OpenAI API key was found. "
            "Run 'ankii key set' or export OPENAI_API_KEY."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            'Audio generation requires AI support. Run: python -m pip install -e ".[ai]"'
        ) from exc
    return OpenAI(api_key=api_key)


def local_voices(language: str | None = None) -> list[LocalVoice]:
    """Return installed macOS voices, optionally filtered by language or locale."""
    if sys.platform != "darwin":
        raise RuntimeError("Local voice discovery currently requires macOS.")
    say = shutil.which("say")
    if not say:
        raise RuntimeError("The macOS 'say' command is unavailable.")
    result = subprocess.run(
        [say, "-v", "?"],
        check=True,
        capture_output=True,
        text=True,
    )
    voices: list[LocalVoice] = []
    for line in result.stdout.splitlines():
        match = re.match(r"^(.*?)\s+([a-z]{2,3}_[A-Z]{2})\s+#", line)
        if match:
            voices.append(LocalVoice(match.group(1).strip(), match.group(2)))
    query = (language or "").strip()
    prefix = LANGUAGE_PREFIXES.get(query, query).casefold().replace("-", "_")
    if prefix:
        voices = [
            voice
            for voice in voices
            if voice.language.casefold() == prefix
            or voice.language.casefold().startswith(f"{prefix}_")
            or prefix in voice.name.casefold()
        ]
    return voices


def load_audio_skips(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid audio skip JSON in {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("audio_skip_version") != AUDIO_SKIP_VERSION:
        raise ValueError(f"{path} is not a supported audio skip file.")
    items = data.get("items")
    if not isinstance(items, dict) or any(
        not isinstance(key, str) or not isinstance(value, dict)
        for key, value in items.items()
    ):
        raise ValueError(f"{path} has invalid skipped audio entries.")
    return items


def save_audio_skips(path: Path, items: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"audio_skip_version": AUDIO_SKIP_VERSION, "items": items},
                stream,
                ensure_ascii=False,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def add_audio_skip(
    existing: dict[str, dict[str, Any]], candidate: MissingAudio, profile: LanguageProfile
) -> dict[str, dict[str, Any]]:
    updated = dict(existing)
    settings = _enabled_settings(profile)
    updated[candidate.filename] = {
        "text": candidate.text,
        "kind": candidate.kind,
        "provider": settings.provider,
        "model": settings.model,
        "voice": settings.voice,
        "language": settings.language,
        "accent": settings.accent,
        "instructions": settings.instructions,
        "skipped_at": datetime.now(UTC).isoformat(),
    }
    return updated


def missing_audio(
    model: str,
    profile: LanguageProfile,
    ignored: set[str] | None = None,
) -> tuple[list[MissingAudio], int]:
    _enabled_settings(profile)
    available_fields = list(invoke("modelFieldNames", modelName=model))
    field_names = infer_field_names(available_fields)
    required = {
        field_names["target"],
        field_names["example_target"],
        field_names["target_audio"],
        field_names["example_audio"],
    }
    absent = required - set(available_fields)
    if absent:
        raise ValueError(
            f"Vocabulary note type {model!r} is missing fields: "
            f"{', '.join(sorted(absent))}. Run 'ankii anki update' first."
        )
    ignored = ignored or set()
    candidates: list[MissingAudio] = []
    ignored_count = 0
    for note in notes_for_model(model, profile.deck):
        note_fields = note.get("fields", {})
        word = _field_value(note_fields, field_names["target"])
        requests = [(word, "target", field_names["target_audio"])]
        combined_example = example_audio_text(
            _field_value(note_fields, field_names["example_target"])
        )
        if combined_example:
            requests.append((combined_example, "example", field_names["example_audio"]))
        for text, kind, field in requests:
            if not text:
                continue
            filename = audio_filename(profile, text)
            existing_value = _field_raw(note_fields, field)
            if AUDIO_REFERENCE_RE.search(existing_value):
                continue
            if filename in ignored:
                ignored_count += 1
                continue
            candidates.append(
                MissingAudio(
                    note_id=int(note["noteId"]),
                    word=word,
                    text=text,
                    kind=kind,
                    field=field,
                    filename=filename,
                    existing_value=existing_value,
                )
            )
    return candidates, ignored_count


def install_missing_audio(
    candidate: MissingAudio,
    profile: LanguageProfile,
    client: Any,
    _current_value: str,
) -> tuple[str, bool]:
    path, generated = ensure_audio_clip(profile, candidate.text, client)
    stored = invoke("storeMediaFile", filename=path.name, path=str(path.resolve()))
    if not isinstance(stored, str) or not stored:
        raise RuntimeError("AnkiConnect returned an invalid stored audio filename.")
    sound = f"[sound:{stored}]"
    updated = sound
    invoke(
        "updateNoteFields",
        note={"id": candidate.note_id, "fields": {candidate.field: updated}},
    )
    return updated, generated


def ensure_audio_clip(
    profile: LanguageProfile, text: str, client: Any, *, retries: int = 3
) -> tuple[Path, bool]:
    settings = _enabled_settings(profile)
    cache_dir = profile.audio_cache_path
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / audio_filename(profile, text)
    if path.is_file() and path.stat().st_size:
        return path, False
    _generate_clip(client, settings, profile, text, path, retries=retries)
    return path, True


def attach_audio(
    entries: list[tuple[dict[str, Any], dict[str, Any]]],
    profile: LanguageProfile,
    field_names: dict[str, str],
    client: Any,
    *,
    retries: int = 3,
) -> AudioGenerationResult:
    settings = _enabled_settings(profile)
    cache_dir = profile.audio_cache_path
    cache_dir.mkdir(parents=True, exist_ok=True)
    generated = cached = 0
    failures: list[AudioFailure] = []

    for note, card in entries:
        if note.get("modelName") == "Grammar":
            continue
        requests = [(str(card.get("word", "")).strip(), field_names["target_audio"])]
        example_value = card.get("example_target", card.get("example_vn", ""))
        combined_example = example_audio_text(example_value)
        if combined_example:
            requests.append((combined_example, field_names["example_audio"]))
        media: list[dict[str, Any]] = []
        for text, field in requests:
            if not text:
                continue
            path = cache_dir / audio_filename(profile, text)
            if path.is_file() and path.stat().st_size:
                cached += 1
            else:
                try:
                    _generate_clip(client, settings, profile, text, path, retries=retries)
                    generated += 1
                except Exception as exc:  # individual clips are intentionally non-fatal
                    failures.append(AudioFailure(text=text, error=str(exc)))
                    continue
            media.append(
                {
                    "path": str(path.resolve()),
                    "filename": path.name,
                    "fields": [field],
                }
            )
        if media:
            note["audio"] = media

    return AudioGenerationResult(generated, cached, tuple(failures))


def _field_raw(fields: dict[str, Any], name: str) -> str:
    value = fields.get(name, {})
    return str(value.get("value", "")).strip() if isinstance(value, dict) else ""


def _field_value(fields: dict[str, Any], name: str) -> str:
    return html.unescape(_field_raw(fields, name)).strip()


def _enabled_settings(profile: LanguageProfile) -> AudioSettings:
    if profile.audio is None or not profile.audio.enabled:
        raise ValueError(f"Audio generation is not enabled for profile {profile.name!r}.")
    return profile.audio


def _generate_clip(
    client: Any,
    settings: AudioSettings,
    profile: LanguageProfile,
    text: str,
    destination: Path,
    *,
    retries: int,
) -> None:
    if retries < 1:
        raise ValueError("Audio generation retries must be at least 1.")
    last_error: Exception | None = None
    for attempt in range(retries):
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            if settings.provider == "local":
                _generate_local_clip(client, settings, text, temporary)
            else:
                with client.audio.speech.with_streaming_response.create(
                    model=settings.model,
                    voice=settings.voice,
                    input=text,
                    instructions=speech_instructions(profile),
                    response_format="mp3",
                ) as response:
                    response.stream_to_file(temporary)
            if not temporary.stat().st_size:
                raise RuntimeError("OpenAI returned an empty audio file.")
            os.replace(temporary, destination)
            return
        except Exception as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
            if attempt + 1 < retries and _is_transient_error(exc):
                time.sleep(2**attempt)
                continue
            break
    assert last_error is not None
    raise last_error


def _generate_local_clip(
    client: LocalSpeechClient,
    settings: AudioSettings,
    text: str,
    destination: Path,
) -> None:
    descriptor, source_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".aiff", dir=destination.parent
    )
    os.close(descriptor)
    source = Path(source_name)
    try:
        subprocess.run(
            [client.say, "-v", settings.voice, "-o", str(source), text],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                client.ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-codec:a",
                "libmp3lame",
                "-f",
                "mp3",
                str(destination),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode(errors="replace").strip() if exc.stderr else str(exc)
        raise RuntimeError(f"Local speech generation failed: {message}") from exc
    finally:
        source.unlink(missing_ok=True)


def _is_transient_error(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and (status in {408, 409, 429} or status >= 500):
        return True
    return type(error).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "RateLimitError",
    }
