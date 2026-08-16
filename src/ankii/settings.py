from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import tomllib
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETTINGS_VERSION = 1
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
AVAILABLE_LANGUAGES = (
    "Arabic",
    "Cantonese",
    "Catalan",
    "Czech",
    "Danish",
    "Dutch",
    "English",
    "Finnish",
    "French",
    "German",
    "Greek",
    "Hebrew",
    "Hindi",
    "Hungarian",
    "Indonesian",
    "Italian",
    "Japanese",
    "Korean",
    "Latin",
    "Malay",
    "Mandarin Chinese",
    "Norwegian",
    "Persian",
    "Polish",
    "Portuguese",
    "Romanian",
    "Russian",
    "Spanish",
    "Swahili",
    "Swedish",
    "Tagalog",
    "Thai",
    "Turkish",
    "Ukrainian",
    "Vietnamese",
)
APP_DIRECTORY_NAME = "ankii"
DEFAULT_SETTINGS_TOML = """settings_version = 1
default_profile = "vietnamese"

[anki]
vocabulary_model = "Vocabulary"
grammar_model = "Grammar"

[profiles.vietnamese]
study_language = "Vietnamese"
native_language = "English"
deck = "Vietnamese"
analysis_min_level = "A1"
analysis_max_level = "B2"

[profiles.french]
study_language = "French"
native_language = "English"
deck = "French"
analysis_min_level = "A1"
analysis_max_level = "B2"
"""


def data_root() -> Path:
    """Return the per-user directory for settings and generated review data."""
    override = os.environ.get("ANKII_HOME") or os.environ.get("YHW2ANKI_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIRECTORY_NAME
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / APP_DIRECTORY_NAME
        return Path.home() / "AppData" / "Local" / APP_DIRECTORY_NAME
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    return (
        Path(xdg_data_home).expanduser() / APP_DIRECTORY_NAME
        if xdg_data_home
        else Path.home() / ".local" / "share" / APP_DIRECTORY_NAME
    )


def default_settings_path() -> Path:
    return data_root() / "anki.toml"


def create_default_settings(path: Path | None = None) -> tuple[Path, bool]:
    """Create a safe starter configuration without overwriting an existing file."""
    destination = path or default_settings_path()
    if destination.exists():
        return destination, False
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(DEFAULT_SETTINGS_TOML, encoding="utf-8")
    return destination, True


@dataclass(frozen=True)
class AudioSettings:
    enabled: bool = False
    provider: str = "openai"
    model: str = "gpt-4o-mini-tts"
    voice: str = "marin"
    language: str = ""
    accent: str = ""
    instructions: str = ""


@dataclass(frozen=True)
class LanguageProfile:
    name: str
    study_language: str
    native_language: str
    deck: str
    analysis_min_level: str
    analysis_max_level: str
    review_base: Path = Path("reviews")
    audio: AudioSettings | None = None

    @property
    def review_root(self) -> Path:
        return self.review_base / self.name

    @property
    def inbox_path(self) -> Path:
        return self.review_root / "inbox.review.json"

    @property
    def grammar_ignore_path(self) -> Path:
        return self.review_root / "grammar-ignore.json"

    @property
    def audio_cache_path(self) -> Path:
        return self.review_root / "audio"

    @property
    def audio_skip_path(self) -> Path:
        return self.review_root / "audio-skip.json"

    @property
    def language_tag(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", self.study_language.casefold()).strip("_")
        return f"language::{slug}"

    @property
    def analysis_levels(self) -> tuple[str, ...]:
        start = CEFR_LEVELS.index(self.analysis_min_level)
        end = CEFR_LEVELS.index(self.analysis_max_level)
        return CEFR_LEVELS[start : end + 1]

    @property
    def is_vietnamese(self) -> bool:
        return self.study_language.casefold() == "vietnamese"


@dataclass(frozen=True)
class Settings:
    default_profile: str
    vocabulary_model: str
    grammar_model: str
    profiles: dict[str, LanguageProfile]
    path: Path

    def select_profile(self, requested: str | None = None) -> LanguageProfile:
        name = requested or os.environ.get("ANKI_PROFILE") or self.default_profile
        try:
            return self.profiles[name]
        except KeyError as exc:
            available = ", ".join(sorted(self.profiles))
            raise ValueError(f"Unknown profile {name!r}. Available profiles: {available}.") from exc


def _required_string(table: dict[str, Any], key: str, context: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}.{key} must be a non-empty string.")
    return value.strip()


def _audio_settings(raw: dict[str, Any], context: str) -> AudioSettings | None:
    value = raw.get("audio")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{context}.audio must be a table.")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"{context}.audio.enabled must be true or false.")
    provider = value.get("provider", "openai")
    local_provider = isinstance(provider, str) and provider.strip().casefold() == "local"
    model = value.get("model", "macos-say" if local_provider else "gpt-4o-mini-tts")
    voice = value.get("voice", "marin")
    language = value.get("language", "")
    accent = value.get("accent", "")
    instructions = value.get("instructions", "")
    for key, item in {
        "provider": provider,
        "model": model,
        "voice": voice,
    }.items():
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{context}.audio.{key} must be a non-empty string.")
    for key, item in {
        "language": language,
        "accent": accent,
        "instructions": instructions,
    }.items():
        if not isinstance(item, str):
            raise ValueError(f"{context}.audio.{key} must be a string.")
    provider = provider.strip().casefold()
    if provider not in {"openai", "local"}:
        raise ValueError(f"{context}.audio.provider must be 'openai' or 'local'.")
    return AudioSettings(
        enabled=enabled,
        provider=provider,
        model=model.strip(),
        voice=voice.strip(),
        language=language.strip(),
        accent=accent.strip(),
        instructions=instructions.strip(),
    )


def load_settings(path: Path | None = None) -> Settings:
    path = path or default_settings_path()
    if not path.exists():
        raise ValueError(
            f"Settings file not found: {path}. Run 'ankii setup' or pass --settings PATH."
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {path}: {exc}") from exc
    if data.get("settings_version") != SETTINGS_VERSION:
        raise ValueError(f"{path} must declare settings_version = {SETTINGS_VERSION}.")
    default_profile = _required_string(data, "default_profile", "settings")
    anki = data.get("anki")
    if not isinstance(anki, dict):
        raise ValueError("settings.anki must be a table.")
    vocabulary_model = _required_string(anki, "vocabulary_model", "anki")
    grammar_model = _required_string(anki, "grammar_model", "anki")
    if vocabulary_model == grammar_model:
        raise ValueError("Anki vocabulary_model and grammar_model must be different.")
    raw_profiles = data.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("settings.profiles must contain at least one profile.")
    profiles: dict[str, LanguageProfile] = {}
    for name, raw in raw_profiles.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(raw, dict):
            raise ValueError("Every profile must be a named TOML table.")
        study = _required_string(raw, "study_language", f"profiles.{name}")
        native = raw.get("native_language", "English")
        if not isinstance(native, str) or not native.strip():
            raise ValueError(f"profiles.{name}.native_language must be a non-empty string.")
        minimum = _required_string(raw, "analysis_min_level", f"profiles.{name}").upper()
        maximum = _required_string(raw, "analysis_max_level", f"profiles.{name}").upper()
        if minimum not in CEFR_LEVELS or maximum not in CEFR_LEVELS:
            raise ValueError(
                f"profiles.{name} levels must be one of {', '.join(CEFR_LEVELS)}."
            )
        if CEFR_LEVELS.index(minimum) > CEFR_LEVELS.index(maximum):
            raise ValueError(f"profiles.{name} analysis level range must be ascending.")
        profiles[name] = LanguageProfile(
            name=name,
            study_language=study,
            native_language=native.strip(),
            deck=_required_string(raw, "deck", f"profiles.{name}"),
            analysis_min_level=minimum,
            analysis_max_level=maximum,
            review_base=path.parent / "reviews",
            audio=_audio_settings(raw, f"profiles.{name}"),
        )
    if default_profile not in profiles:
        raise ValueError(f"default_profile {default_profile!r} is not defined in profiles.")
    return Settings(default_profile, vocabulary_model, grammar_model, profiles, path)


DEFAULT_PROFILE = LanguageProfile("vietnamese", "Vietnamese", "English", "Vietnamese", "A1", "B2")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def canonical_language(value: str) -> str:
    normalized = value.strip().casefold()
    matches = {language.casefold(): language for language in AVAILABLE_LANGUAGES}
    try:
        return matches[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unknown language {value!r}. Run 'ankii profile languages' to list available values."
        ) from exc


def profile_name_for_language(language: str) -> str:
    canonical = canonical_language(language)
    ascii_name = unicodedata.normalize("NFKD", canonical).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.casefold()).strip("-")


def _validated_profile_name(name: str) -> str:
    normalized = name.strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized):
        raise ValueError(
            "Profile names must start with a lowercase letter or number and contain only "
            "lowercase letters, numbers, hyphens, or underscores."
        )
    return normalized


def _replace_default_profile(text: str, name: str) -> str:
    updated, count = re.subn(
        r"(?m)^default_profile\s*=.*$",
        f"default_profile = {_toml_string(name)}",
        text,
        count=1,
    )
    if count != 1:
        raise ValueError("Settings must contain one top-level default_profile value.")
    return updated


def _write_validated_settings(path: Path, text: str) -> Settings:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.chmod(path.stat().st_mode & 0o777)
        load_settings(temporary)
        os.replace(temporary, path)
    finally:
        with suppress(OSError):
            temporary.unlink()
    return load_settings(path)


def add_profile(
    path: Path,
    name: str,
    study_language: str,
    native_language: str,
    deck: str,
    analysis_min_level: str,
    analysis_max_level: str,
    *,
    make_default: bool = False,
) -> LanguageProfile:
    settings = load_settings(path)
    name = _validated_profile_name(name)
    if name in settings.profiles:
        raise ValueError(f"Profile {name!r} already exists.")
    values = {
        "study_language": canonical_language(study_language),
        "native_language": canonical_language(native_language),
        "deck": deck.strip(),
    }
    for key, value in values.items():
        if not value:
            raise ValueError(f"Profile {key.replace('_', ' ')} must not be empty.")
    minimum = analysis_min_level.strip().upper()
    maximum = analysis_max_level.strip().upper()
    if minimum not in CEFR_LEVELS or maximum not in CEFR_LEVELS:
        raise ValueError(f"Profile levels must be one of {', '.join(CEFR_LEVELS)}.")
    if CEFR_LEVELS.index(minimum) > CEFR_LEVELS.index(maximum):
        raise ValueError("Profile analysis level range must be ascending.")

    block = (
        f"\n[profiles.{name}]\n"
        f"study_language = {_toml_string(values['study_language'])}\n"
        f"native_language = {_toml_string(values['native_language'])}\n"
        f"deck = {_toml_string(values['deck'])}\n"
        f"analysis_min_level = {_toml_string(minimum)}\n"
        f"analysis_max_level = {_toml_string(maximum)}\n"
    )
    text = path.read_text(encoding="utf-8").rstrip() + "\n" + block
    if make_default:
        text = _replace_default_profile(text, name)
    updated = _write_validated_settings(path, text)
    profile = updated.profiles[name]
    profile.review_root.mkdir(parents=True, exist_ok=True)
    return profile


def set_default_profile(path: Path, name: str) -> Settings:
    settings = load_settings(path)
    name = name.strip()
    if name not in settings.profiles:
        available = ", ".join(sorted(settings.profiles))
        raise ValueError(f"Unknown profile {name!r}. Available profiles: {available}.")
    text = _replace_default_profile(path.read_text(encoding="utf-8"), name)
    return _write_validated_settings(path, text)


def set_profile_audio(path: Path, name: str, audio: AudioSettings) -> LanguageProfile:
    """Create or replace one profile's audio table without rewriting unrelated TOML."""
    settings = load_settings(path)
    name = name.strip()
    if name not in settings.profiles:
        available = ", ".join(sorted(settings.profiles))
        raise ValueError(f"Unknown profile {name!r}. Available profiles: {available}.")

    block = (
        f"[profiles.{name}.audio]\n"
        f"enabled = {'true' if audio.enabled else 'false'}\n"
        f"provider = {_toml_string(audio.provider)}\n"
        f"model = {_toml_string(audio.model)}\n"
        f"voice = {_toml_string(audio.voice)}\n"
        f"language = {_toml_string(audio.language)}\n"
        f"accent = {_toml_string(audio.accent)}\n"
        f"instructions = {_toml_string(audio.instructions)}\n"
    )
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    header = f"[profiles.{name}.audio]"
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == header),
        None,
    )
    if start is None:
        profile_header = f"[profiles.{name}]"
        profile_start = next(
            index for index, line in enumerate(lines) if line.strip() == profile_header
        )
        nested_prefix = f"[profiles.{name}."
        insert_at = len(lines)
        for index in range(profile_start + 1, len(lines)):
            section = lines[index].strip()
            if section.startswith("[") and not section.startswith(nested_prefix):
                insert_at = index
                break
        prefix = "".join(lines[:insert_at]).rstrip()
        suffix = "".join(lines[insert_at:]).lstrip("\n")
        updated_text = f"{prefix}\n\n{block}"
        if suffix:
            updated_text += f"\n{suffix}"
    else:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if lines[index].strip().startswith("["):
                end = index
                break
        replacement = block + ("\n" if end < len(lines) else "")
        updated_text = "".join([*lines[:start], replacement, *lines[end:]]).rstrip() + "\n"
    updated = _write_validated_settings(path, updated_text)
    return updated.profiles[name]


def delete_profile(
    path: Path, name: str, *, new_default: str | None = None
) -> tuple[Settings, Path]:
    settings = load_settings(path)
    name = name.strip()
    if name not in settings.profiles:
        available = ", ".join(sorted(settings.profiles))
        raise ValueError(f"Unknown profile {name!r}. Available profiles: {available}.")
    remaining = [profile_name for profile_name in settings.profiles if profile_name != name]
    if not remaining:
        raise ValueError("The only profile cannot be deleted. Create another profile first.")
    if name == settings.default_profile:
        if new_default is None:
            raise ValueError("Deleting the default profile requires a new default profile.")
        if new_default not in remaining:
            available = ", ".join(sorted(remaining))
            raise ValueError(f"New default must be one of: {available}.")
    elif new_default is not None:
        if new_default not in remaining:
            available = ", ".join(sorted(remaining))
            raise ValueError(f"New default must be one of: {available}.")

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    header = f"[profiles.{name}]"
    try:
        start = next(index for index, line in enumerate(lines) if line.strip() == header)
    except StopIteration as exc:
        raise ValueError(f"Could not locate the TOML table for profile {name!r}.") from exc
    nested_prefix = f"[profiles.{name}."
    end = len(lines)
    for index in range(start + 1, len(lines)):
        section = lines[index].strip()
        if section.startswith("[") and not section.startswith(nested_prefix):
            end = index
            break
    updated_text = "".join([*lines[:start], *lines[end:]]).rstrip() + "\n"
    if new_default is not None:
        updated_text = _replace_default_profile(updated_text, new_default)
    review_root = settings.profiles[name].review_root
    updated = _write_validated_settings(path, updated_text)
    return updated, review_root
