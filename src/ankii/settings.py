from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import tomllib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SETTINGS_VERSION = 1
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")
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
class LanguageProfile:
    name: str
    study_language: str
    native_language: str
    deck: str
    analysis_min_level: str
    analysis_max_level: str
    review_base: Path = Path("reviews")

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
        )
    if default_profile not in profiles:
        raise ValueError(f"default_profile {default_profile!r} is not defined in profiles.")
    return Settings(default_profile, vocabulary_model, grammar_model, profiles, path)


DEFAULT_PROFILE = LanguageProfile("vietnamese", "Vietnamese", "English", "Vietnamese", "A1", "B2")


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


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
        "study_language": study_language.strip(),
        "native_language": native_language.strip(),
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
