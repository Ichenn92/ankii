from __future__ import annotations

import argparse
import html
import json
import os
import sys
import unicodedata
import urllib.error
from collections import Counter
from pathlib import Path

from ankii.analyzer import (
    AnalysisCandidate,
    PassageAnalysis,
    analyze_passage,
    known_anki_headwords,
    normalize_headword,
)
from ankii.anki import AnkiConnectError, invoke
from ankii.commons import open_gallery, search_commons
from ankii.grammar_check import (
    GrammarSuggestion,
    add_rejections,
    discover_grammar,
    load_ignored,
    save_ignored,
)
from ankii.importer import (
    GENERIC_FIELD_DEFAULTS,
    add_notes,
    build_grammar_note,
    infer_field_names,
    prepare_import,
)
from ankii.inbox import (
    append_card,
    append_cards,
    archive_completed_review,
    archive_imported_cards,
    load_or_create_inbox,
)
from ankii.keychain import (
    delete_keychain_key,
    get_openai_api_key,
    keychain_supported,
    store_keychain_key,
)
from ankii.maintenance import apply_reimport, apply_retags, prepare_reimport, retag_notes
from ankii.note_type import backfill_examples, setup_learning_models, setup_note_type
from ankii.review import (
    AI_TAG_PREFIXES,
    ALLOWED_AI_TAGS,
    create_review,
    has_complete_ai_taxonomy,
    load_review,
    new_import_id,
    save_review,
    save_review_atomic,
    validate_review_profile,
)
from ankii.settings import (
    AVAILABLE_LANGUAGES,
    CEFR_LEVELS,
    DEFAULT_PROFILE,
    LanguageProfile,
    add_profile,
    canonical_language,
    create_default_settings,
    data_root,
    default_settings_path,
    delete_profile,
    load_settings,
    profile_name_for_language,
    set_default_profile,
)
from ankii.tagging import suggest_card_tags, suggest_example_sentence, tag_review
from ankii.tone_family import (
    TONE_LABELS,
    VOCABULARY_LINK_FIELD,
    ToneFamily,
    build_tone_family_note,
    build_tone_vocabulary_note,
    generate_tone_family,
    normalize_syllable,
    setup_tone_family_model,
    setup_vocabulary_tone_link,
    tone_family_from_review,
    tone_family_link,
    tone_family_to_review,
)
from ankii.yourhomework import fetch_lesson


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ankii",
        description="Review, tag, and import YourHomework vocabulary into Anki.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
epilog="""Examples:
  ankii add "xin chào"
  ankii import
  ankii yhw wizard 313789981

Run 'ankii COMMAND --help' for help with a specific command.""",
    )
    parser.add_argument("--profile", help="Language profile from anki.toml.")
    parser.add_argument(
        "--settings",
        type=Path,
        default=default_settings_path(),
        help="Settings TOML (default: the per-user ankii data directory).",
    )
    commands = parser.add_subparsers(dest="command")

    setup_parser = commands.add_parser(
        "setup", help="Create local settings and securely configure the OpenAI API key."
    )
    setup_parser.add_argument(
        "--skip-key",
        action="store_true",
        help="Create local files without prompting to store an OpenAI API key.",
    )

    profile_parser = commands.add_parser("profile", help="Create and configure study profiles.")
    profile_commands = profile_parser.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("languages", help="List languages accepted by profile creation.")
    profile_commands.add_parser("list", help="List configured profiles.")
    create_profile_parser = profile_commands.add_parser(
        "create", help="Create a new language profile."
    )
    create_profile_parser.add_argument(
        "name", nargs="?", help="Profile name (default: lowercase study language)."
    )
    create_profile_parser.add_argument("--study-language", type=_language_argument)
    create_profile_parser.add_argument("--native-language", type=_language_argument)
    create_profile_parser.add_argument("--deck")
    create_profile_parser.add_argument("--min-level", choices=CEFR_LEVELS)
    create_profile_parser.add_argument("--max-level", choices=CEFR_LEVELS)
    create_profile_parser.add_argument(
        "--default", action="store_true", help="Also make the new profile the default."
    )
    default_profile_parser = profile_commands.add_parser(
        "default", help="Set the default language profile."
    )
    default_profile_parser.add_argument("name", nargs="?", help="Existing profile name.")
    delete_profile_parser = profile_commands.add_parser(
        "delete", help="Remove a profile while preserving its review files."
    )
    delete_profile_parser.add_argument("name", nargs="?", help="Existing profile name.")
    delete_profile_parser.add_argument(
        "--new-default",
        help="Replacement default profile (required when deleting the current default).",
    )
    delete_profile_parser.add_argument(
        "--yes",
        action="store_true",
        help="Delete without asking for confirmation.",
    )

    add_parser = commands.add_parser("add", help="Add a card to the manual vocabulary inbox.")
    add_parser.add_argument(
        "word", nargs="?", help="Studied-language word (prompted when omitted)."
    )
    add_parser.add_argument(
        "--inbox",
        type=Path,
        default=None,
        help="Inbox review JSON (default: active profile inbox).",
    )

    analyze_parser = commands.add_parser(
        "analyze", help="Analyze studied-language text and choose learning cards."
    )
    analyze_parser.add_argument(
        "text", nargs="?", help="Passage (read from stdin or prompted when omitted)."
    )

    tones_parser = commands.add_parser(
        "tones", help="Generate a Southern Vietnamese tone-family review JSON."
    )
    tones_parser.add_argument("syllable", help="One Vietnamese syllable, with or without tone.")
    tones_parser.add_argument("--output", type=Path, help="Review JSON output path.")
    tones_parser.add_argument(
        "--model", default="ToneFamily", help="Anki note type (default: ToneFamily)."
    )
    tones_parser.add_argument(
        "--vocabulary-model",
        default="Vocabulary",
        help="Vocabulary note type (default: Vocabulary).",
    )
    tones_parser.add_argument(
        "--ai-model",
        default=os.environ.get("OPENAI_MODEL", "gpt-5.6-sol"),
        help="OpenAI model (default: OPENAI_MODEL or gpt-5.6-sol).",
    )
    analyze_parser.add_argument("--source-title", default=None)
    analyze_parser.add_argument("--source-url", default=None)
    analyze_parser.add_argument("--inbox", type=Path, default=None)
    analyze_parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL", "gpt-5.6-sol"),
        help="OpenAI model (default: OPENAI_MODEL or gpt-5.6-sol).",
    )

    yhw_parser = commands.add_parser(
        "yhw",
        help="Import vocabulary lessons from yourhomework.net.",
        description="Fetch and review public vocabulary lessons from https://yourhomework.net.",
    )
    yhw_commands = yhw_parser.add_subparsers(dest="yhw_command", required=True)

    fetch_parser = yhw_commands.add_parser(
        "fetch",
        help="Download and normalize a public yourhomework.net vocabulary lesson.",
    )
    fetch_parser.add_argument("lesson", help="Numeric public ID or complete vocabulary URL.")
    fetch_parser.add_argument("--output", type=Path)

    review_parser = yhw_commands.add_parser(
        "review",
        help="Create a local review file from a yourhomework.net vocabulary lesson.",
    )
    review_parser.add_argument("lesson", help="Numeric public ID or complete vocabulary URL.")
    review_parser.add_argument("--output", type=Path)

    tag_parser = commands.add_parser("tag", help="Add GPT tag suggestions to a review file.")
    tag_parser.add_argument("review_file", type=Path)
    tag_parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL", "gpt-5.6-sol"),
        help="OpenAI model (default: OPENAI_MODEL or gpt-5.6-sol).",
    )

    approve_parser = commands.add_parser("approve", help="Interactively approve review cards.")
    approve_parser.add_argument(
        "review_file",
        nargs="?",
        type=Path,
        help="Review JSON (prompted from the active profile when omitted).",
    )

    wizard_parser = yhw_commands.add_parser(
        "wizard",
        help="Guide the complete yourhomework.net-to-Anki workflow.",
    )
    wizard_parser.add_argument(
        "lesson",
        nargs="?",
        help="Numeric public ID or complete vocabulary URL (prompted when omitted).",
    )

    key_parser = commands.add_parser("key", help="Manage the OpenAI key in macOS Keychain.")
    key_commands = key_parser.add_subparsers(dest="key_command", required=True)
    key_commands.add_parser("set", help="Securely add or replace the stored API key.")
    key_commands.add_parser("status", help="Show whether a key is available without revealing it.")
    key_commands.add_parser("delete", help="Delete the stored API key from Keychain.")

    anki_parser = commands.add_parser("anki", help="Inspect the local Anki collection.")
    anki_commands = anki_parser.add_subparsers(dest="anki_command", required=True)
    anki_commands.add_parser("status", help="Check the AnkiConnect connection.")
    anki_commands.add_parser("decks", help="List decks.")
    anki_commands.add_parser("models", help="List note types.")
    fields_parser = anki_commands.add_parser("fields", help="List fields for a note type.")
    fields_parser.add_argument("model")
    setup_parser = anki_commands.add_parser(
        "setup-note-type",
        help="Add example fields, migrate legacy values, and update card backs.",
    )
    setup_parser.add_argument(
        "model",
        nargs="?",
        help="Exact note type name (prompted when omitted).",
    )
    setup_models_parser = anki_commands.add_parser(
        "setup-note-types",
        help="Migrate Vietnamese to Vocabulary and create a matching Grammar note type.",
    )
    setup_models_parser.add_argument(
        "source", nargs="?", default=None, help="Existing language-specific vocabulary note type."
    )

    import_parser = commands.add_parser(
        "import",
        help="Import approved cards into Anki.",
        description=(
            "Import approved cards. The JSON card_type selects Vocabulary or Grammar "
            "for each card. Missing file and deck arguments are selected interactively."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
epilog="""Examples:
  ankii import
  ankii import "$HOME/Library/Application Support/ankii/reviews/vietnamese/inbox.review.json"
  ankii --profile french import /path/to/review.json""",
    )
    import_parser.add_argument(
        "review_file",
        nargs="?",
        type=Path,
        help="Review JSON (prompted from the active profile's local data directory when omitted).",
    )
    import_parser.add_argument("--deck", default=None, help=argparse.SUPPRESS)
    import_parser.add_argument(
        "--model",
        default="Vocabulary",
        help="Vocabulary note type (default: shared model from anki.toml).",
    )
    import_parser.add_argument(
        "--grammar-model",
        default="Grammar",
        help="Grammar note type (default: shared model from anki.toml).",
    )
    import_parser.add_argument(
        "--tone-model",
        default=None,
        help="Note type for tone-family recap cards (default: saved value or ToneFamily).",
    )
    for key, default in GENERIC_FIELD_DEFAULTS.items():
        import_parser.add_argument(
            f"--field-{key.replace('_', '-')}",
            default=None,
            help=(
                f"Anki field for {key.replace('_', ' ')} "
                f"(automatically detected; fallback: {default})."
            ),
        )

    backfill_parser = commands.add_parser(
        "backfill-examples",
        help="Fill empty example fields on existing Anki notes from a review file.",
    )
    backfill_parser.add_argument("review_file", type=Path)
    backfill_parser.add_argument("--model", required=True)

    retag_parser = commands.add_parser(
        "retag", help="Recalculate taxonomy tags on every note of an Anki note type."
    )
    retag_parser.add_argument("--all", action="store_true", required=True)
    retag_parser.add_argument("--model", required=True, help="Exact Anki note type name.")
    retag_parser.add_argument("--ai-model", default=os.environ.get("OPENAI_MODEL", "gpt-5.6-sol"))

    reimport_parser = commands.add_parser(
        "reimport", help="Update existing Anki notes from all local review files."
    )
    reimport_parser.add_argument("--all", action="store_true")
    reimport_parser.add_argument("--reviews", type=Path)
    reimport_parser.add_argument("--model")
    reimport_parser.add_argument("--deck", default=None, help=argparse.SUPPRESS)

    grammar_parser = commands.add_parser(
        "grammar-check",
        help="Find grammar in Vocabulary examples that is missing from Grammar.",
    )
    grammar_parser.add_argument("--all", action="store_true", required=True)
    grammar_parser.add_argument("--model", default=None)
    grammar_parser.add_argument("--grammar-model", default=None)
    grammar_parser.add_argument("--deck", default=None, help=argparse.SUPPRESS)
    grammar_parser.add_argument("--ai-model", default=os.environ.get("OPENAI_MODEL", "gpt-5.6-sol"))
    grammar_parser.add_argument(
        "--ignore-file", type=Path, default=None
    )
    return parser


def _language_argument(value: str) -> str:
    try:
        return canonical_language(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def run_fetch(lesson_value: str, output: Path | None) -> int:
    lesson = fetch_lesson(lesson_value)
    output_path = output or data_root() / "downloads" / f"lesson-{lesson.public_id}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(lesson.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Lesson: {lesson.title}")
    print(f"Words:  {len(lesson.items)}")
    print(f"Saved:  {output_path}")
    return 0


def run_review(
    lesson_value: str, output: Path | None, profile: LanguageProfile = DEFAULT_PROFILE
) -> int:
    lesson = fetch_lesson(lesson_value)
    output_path = output or profile.review_root / f"{lesson.public_id}.review.json"
    if output_path.exists():
        raise ValueError(f"Review file already exists: {output_path}")
    save_review(create_review(lesson, profile), output_path)
    print(f"Lesson: {lesson.title}")
    print(f"Cards:  {len(lesson.items)}")
    print(f"Saved:  {output_path}")
    return 0


def _edit_card(card: dict[str, object], profile: LanguageProfile = DEFAULT_PROFILE) -> None:
    for key, label in (
        ("word", profile.study_language),
        ("meaning", profile.native_language),
        ("example_target", f"Example {profile.study_language}"),
        ("example_native", f"Example {profile.native_language}"),
    ):
        current = str(card.get(key, ""))
        value = input(f"{label} [{current}]: ").strip()
        if value:
            card[key] = value


def run_approve(path: Path, profile: LanguageProfile = DEFAULT_PROFILE) -> int:
    review = load_review(path)
    validate_review_profile(review, profile)
    cards = review["cards"]
    for index, card in enumerate(cards):
        if card["approved"] or card["skip"]:
            continue
        while True:
            print(f"\n[{index + 1}/{len(cards)}] {card['word']} -> {card['meaning']}")
            if card.get("example_vn"):
                print(f"Example: {card['example_vn']}")
            print(f"Tags:    {' '.join(card['tags'])}")
            choice = input("[a]pprove [e]dit [s]kip approve [A]ll [q]uit: ").strip()
            if choice == "a":
                card["approved"] = True
                break
            if choice == "e":
                _edit_card(card, profile)
                continue
            if choice == "s":
                card["skip"] = True
                break
            if choice == "A":
                for remaining in cards[index:]:
                    if not remaining["skip"]:
                        remaining["approved"] = True
                save_review(review, path)
                print(f"Approved all remaining cards and saved {path}")
                return 0
            if choice == "q":
                save_review(review, path)
                print(f"Saved progress to {path}")
                return 0
            print("Choose a, e, s, A, or q.")
        save_review(review, path)
    print(f"Review complete and saved to {path}")
    return 0


def run_anki(
    command: str,
    model: str | None = None,
    profile: LanguageProfile = DEFAULT_PROFILE,
    vocabulary_model: str = "Vocabulary",
    grammar_model: str = "Grammar",
) -> int:
    if command == "status":
        version = invoke("version")
        print(f"Connected to AnkiConnect (API version {version}).")
    elif command == "decks":
        print("\n".join(invoke("deckNames")))
    elif command == "models":
        print("\n".join(invoke("modelNames")))
    elif command == "fields" and model is not None:
        print("\n".join(invoke("modelFieldNames", modelName=model)))
    elif command == "setup-note-type" and model is not None:
        print(
            "This will add bilingual example fields if needed, copy legacy example values without "
            "overwriting data, and update every card back for this note type."
        )
        if input("Type UPDATE to continue: ").strip() != "UPDATE":
            print("Update cancelled. No changes were made.")
            return 0
        result = setup_note_type(model)
        print(f"Fields added:      {result['fields_added']}")
        print(f"Notes migrated:    {result['notes_migrated']}")
        print(f"Templates updated: {result['templates_updated']}")
        print(f"Styling updated:   {result['styling_updated']}")
    elif command == "setup-note-type":
        models = sorted(invoke("modelNames"), key=str.casefold)
        preferred = next(
            (name for name in models if "vietnamese" in name.casefold()),
            None,
        )
        selected_model = _choose("note type", models, preferred)
        return run_anki(command, selected_model)
    elif command == "setup-note-types":
        source_model = model or profile.study_language
        print(
            f"This will migrate {source_model!r} into generic {vocabulary_model!r} fields and "
            f"create or refresh {grammar_model!r}."
        )
        if input("Type UPDATE to continue: ").strip() != "UPDATE":
            print("Update cancelled. No changes were made.")
            return 0
        result = setup_learning_models(source_model, vocabulary_model, grammar_model)
        decks = invoke("deckNames")
        if profile.deck not in decks:
            invoke("createDeck", deck=profile.deck)
        escaped_model = vocabulary_model.replace('"', '\\"')
        escaped_deck = profile.deck.replace('"', '\\"')
        note_ids = invoke(
            "findNotes", query=f'note:"{escaped_model}" deck:"{escaped_deck}"'
        )
        if note_ids:
            invoke("addTags", notes=note_ids, tags=profile.language_tag)
        print(f"Vocabulary model created: {result['vocabulary_created']}")
        print(f"Vocabulary notes migrated: {result['notes_migrated']}")
        print(f"Grammar model created: {result['grammar_created']}")
        print(f"Profile deck: {profile.deck}")
        print("The original source note type is left empty and can be removed in Anki.")
    return 0


def run_key(command: str) -> int:
    if command == "set":
        store_keychain_key()
        print("OpenAI API key saved securely in macOS Keychain.")
    elif command == "status":
        key, source = get_openai_api_key()
        if key:
            print(f"OpenAI API key is available from {source}.")
        else:
            print("No OpenAI API key is configured.")
            return 1
    elif command == "delete":
        if delete_keychain_key():
            print("Stored OpenAI API key deleted from macOS Keychain.")
        else:
            print("No stored OpenAI API key was found.")
    return 0


def run_setup(settings_path: Path, *, skip_key: bool = False) -> int:
    settings_path, created = create_default_settings(settings_path)
    settings = load_settings(settings_path)
    for profile in settings.profiles.values():
        profile.review_root.mkdir(parents=True, exist_ok=True)

    action = "Created" if created else "Using"
    print(f"{action} settings: {settings_path}")
    print(f"Local data: {settings_path.parent}")
    print(f"Reviews: {settings_path.parent / 'reviews'}")

    key, source = get_openai_api_key()
    if key:
        print(f"OpenAI API key is already available from {source}.")
        return 0
    if skip_key:
        print("OpenAI API key setup skipped.")
        return 0
    if not keychain_supported():
        print("macOS Keychain is unavailable; set OPENAI_API_KEY in your environment.")
        return 0
    answer = input("Store an OpenAI API key securely in macOS Keychain now? [Y/n]: ").strip()
    if answer.casefold() in {"", "y", "yes"}:
        store_keychain_key()
        print("OpenAI API key saved securely in macOS Keychain.")
    else:
        print("OpenAI API key setup skipped. Run 'ankii key set' whenever you are ready.")
    return 0


def _profile_value(label: str, provided: str | None, default: str | None = None) -> str:
    if provided is not None:
        return provided
    if default is None:
        return _required_input(label)
    return input(f"{label} [{default}]: ").strip() or default


def run_profile(args: argparse.Namespace, settings_path: Path) -> int:
    if args.profile_command == "languages":
        print("Available languages:")
        for language in AVAILABLE_LANGUAGES:
            print(f"  {language}")
        return 0
    settings = load_settings(settings_path)
    if args.profile_command == "list":
        print("Configured profiles:")
        for name, profile in settings.profiles.items():
            marker = " (default)" if name == settings.default_profile else ""
            print(
                f"  {name}{marker}: {profile.study_language} -> "
                f"{profile.native_language} [{profile.deck}]"
            )
        return 0
    if args.profile_command == "default":
        name = args.name or _choose(
            "profile", sorted(settings.profiles), preferred=settings.default_profile
        )
        updated = set_default_profile(settings_path, name)
        print(f"Default profile: {updated.default_profile}")
        return 0
    if args.profile_command == "delete":
        name = args.name or _choose(
            "profile to delete", sorted(settings.profiles), preferred=settings.default_profile
        )
        new_default = args.new_default
        if name == settings.default_profile and new_default is None:
            remaining = sorted(
                profile_name for profile_name in settings.profiles if profile_name != name
            )
            new_default = _choose("new default profile", remaining)
        if not args.yes:
            confirmation = input(f"Type DELETE to remove profile {name!r}: ").strip()
            if confirmation != "DELETE":
                print("Profile deletion cancelled. Nothing was changed.")
                return 0
        _updated, review_root = delete_profile(
            settings_path, name, new_default=new_default
        )
        print(f"Deleted profile: {name}")
        print(f"Review files preserved at: {review_root}")
        if new_default is not None:
            print(f"Default profile: {new_default}")
        return 0

    study_language = args.study_language or _choose(
        "study language",
        list(AVAILABLE_LANGUAGES),
        preferred=settings.select_profile().study_language,
    )
    default_name = profile_name_for_language(study_language)
    name = args.name or default_name
    native_language = args.native_language or _choose(
        "native language", list(AVAILABLE_LANGUAGES), preferred="English"
    )
    deck = _profile_value("Anki deck", args.deck, study_language)
    minimum = args.min_level or _choose("minimum CEFR level", list(CEFR_LEVELS), "A1")
    maximum = args.max_level or _choose("maximum CEFR level", list(CEFR_LEVELS), "B2")
    profile = add_profile(
        settings_path,
        name,
        study_language,
        native_language,
        deck,
        minimum,
        maximum,
        make_default=args.default,
    )
    print(f"Created profile: {profile.name}")
    print(f"Languages: {profile.study_language} -> {profile.native_language}")
    print(f"Anki deck: {profile.deck}")
    print(f"Reviews: {profile.review_root}")
    if args.default:
        print(f"Default profile: {profile.name}")
    return 0


def _choose(label: str, values: list[str], preferred: str | None = None) -> str:
    if not values:
        raise ValueError(f"There are no available {label.lower()} choices.")
    default_index = values.index(preferred) if preferred in values else 0
    print(f"\nChoose {label}:")
    for index, value in enumerate(values, start=1):
        suffix = " (recommended)" if index - 1 == default_index else ""
        print(f"  {index}. {value}{suffix}")
    while True:
        raw = input(f"{label} [{default_index + 1}]: ").strip()
        if not raw:
            return values[default_index]
        if raw.isdigit() and 1 <= int(raw) <= len(values):
            return values[int(raw) - 1]
        print(f"Enter a number from 1 to {len(values)}.")


def _available_review_files() -> list[Path]:
    candidates = set(Path.cwd().glob("*.review.json"))
    reviews_dir = Path("reviews")
    if reviews_dir.is_dir():
        candidates.update(reviews_dir.rglob("*.review.json"))
    return sorted(
        (path for path in candidates if "archive" not in path.parts),
        key=lambda path: str(path).casefold(),
    )


def _available_profile_review_files(profile: LanguageProfile) -> list[Path]:
    if not profile.review_root.is_dir():
        return []
    return sorted(
        (
            path
            for path in profile.review_root.rglob("*.review.json")
            if "archive" not in path.parts
        ),
        key=lambda path: str(path).casefold(),
    )


def _resolve_approve_file(
    path: Path | None, profile: LanguageProfile = DEFAULT_PROFILE
) -> Path:
    if path is not None:
        return path
    candidates: list[Path] = []
    for candidate in _available_profile_review_files(profile):
        try:
            review = load_review(candidate)
            validate_review_profile(review, profile)
        except (OSError, ValueError):
            continue
        if any(not card["approved"] and not card["skip"] for card in review["cards"]):
            candidates.append(candidate)
    if not candidates:
        raise ValueError(f"No reviews with pending cards were found for profile {profile.name!r}.")
    selected = _choose("review file", [str(candidate) for candidate in candidates])
    return Path(selected)


def _available_review_roots() -> list[Path]:
    roots: set[Path] = set()
    reviews = Path("reviews")
    if reviews.is_dir() and any(reviews.rglob("*.json")):
        roots.add(reviews)
        roots.update(
            child
            for child in reviews.iterdir()
            if child.is_dir()
            and child.name != "archive"
            and any(child.rglob("*.json"))
        )
    if any(Path.cwd().glob("*.review.json")):
        roots.add(Path("."))
    return sorted(roots, key=lambda path: str(path).casefold())


def _resolve_reimport_options(
    reviews: Path | None,
    model: str | None,
    profile: LanguageProfile | str | None = DEFAULT_PROFILE,
) -> tuple[Path, str, str]:
    if not isinstance(profile, LanguageProfile):
        legacy_deck = profile
        if reviews is None:
            roots = _available_review_roots()
            reviews = Path(_choose("review collection", [str(path) for path in roots], "reviews"))
        if legacy_deck is None:
            decks = sorted(invoke("deckNames"), key=str.casefold)
            legacy_deck = _choose("deck", decks, "Vietnamese")
        if model is None:
            models = sorted(invoke("modelNames"), key=str.casefold)
            model = _choose("note type", models, "Vocabulary")
        return reviews, model, legacy_deck
    if reviews is None:
        roots = _available_review_roots()
        selected = _choose(
            "review collection",
            [str(path) for path in roots],
            str(profile.review_root),
        )
        reviews = Path(selected)
    if model is None:
        models = sorted(invoke("modelNames"), key=str.casefold)
        model = _choose("note type", models, "Vocabulary")
    return reviews, model, profile.deck


def _resolve_import_destination(
    args: argparse.Namespace, profile: LanguageProfile = DEFAULT_PROFILE
) -> None:
    if args.review_file is None:
        review_files = _available_profile_review_files(profile)
        if not review_files and profile == DEFAULT_PROFILE:
            review_files = _available_review_files()
        if not review_files:
            raise ValueError(
                "No review files were found. Create one with 'ankii add' or "
                "'ankii yhw review LESSON'."
            )
        selected = _choose("review file", [str(path) for path in review_files])
        args.review_file = Path(selected)

    args.deck = profile.deck

    if args.model is None:
        # Names are deterministic so mixed review files never require a single-model
        # choice. ``None`` remains possible for callers constructing a Namespace.
        args.model = "Vocabulary"


def _required_input(label: str, current: str = "") -> str:
    while True:
        suffix = f" [{current}]" if current else ""
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if current:
            return current
        print(f"{label} is required.")


def _read_analysis_text(
    argument: str | None, profile: LanguageProfile = DEFAULT_PROFILE
) -> str:
    if argument and argument.strip():
        return argument.strip()
    if not sys.stdin.isatty():
        value = sys.stdin.read().strip()
        if value:
            return value
        raise ValueError(f"No {profile.study_language} passage was provided on stdin.")
    print(f"Paste {profile.study_language} text. Finish with a line containing only '.':")
    lines: list[str] = []
    while True:
        line = input()
        if line == ".":
            break
        lines.append(line)
    value = "\n".join(lines).strip()
    if not value:
        raise ValueError(f"A {profile.study_language} passage is required.")
    return value


def _resolve_analysis_sources(source_title: str | None, source_url: str | None) -> tuple[str, str]:
    interactive = sys.stdin.isatty()
    if source_title is None:
        source_title = input("Source title (optional): ").strip() if interactive else ""
    if source_url is None:
        source_url = input("Source URL (optional): ").strip() if interactive else ""
    return source_title.strip(), source_url.strip()


def _display_analysis_summary(analysis: PassageAnalysis) -> None:
    print(f"\nTranslation\n{analysis.translation}")
    print(f"\nInterpretation\n{analysis.interpretation}")
    print(f"\nStyle: {', '.join(analysis.styles)}\n{analysis.style_explanation}")
    if analysis.grammar:
        print("\nGrammar")
        for pattern, explanation in analysis.grammar:
            print(f"  - {pattern}: {explanation}")


def _display_analysis_candidate(
    candidate: AnalysisCandidate,
    index: int,
    total: int,
    known: set[str],
    inbox_words: set[str],
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> None:
    key = normalize_headword(candidate.word)
    status = ""
    if key in known:
        status = " [known in Anki]"
    elif key in inbox_words:
        status = " [already in inbox]"
    kind = "grammar" if candidate.card_type == "grammar" else "vocabulary"
    level = next(
        (tag.removeprefix("level::") for tag in candidate.tags if tag.startswith("level::")),
        "unknown level",
    )
    print(f"\n[{index}/{total}] [{kind} · {level}] {candidate.word}{status}")
    print(f"Meaning:   {candidate.meaning}")
    print(f"Why:       {candidate.rationale}")
    print(f"Source:    {candidate.example_vn} — {candidate.example_en}")
    print(
        f"Everyday {profile.analysis_max_level}: "
        f"{candidate.everyday_example_vn} — {candidate.everyday_example_en}"
    )
    print(
        f"Simple {profile.analysis_min_level}:   "
        f"{candidate.simple_example_vn} — {candidate.simple_example_en}"
    )


def run_analyze(
    text_argument: str | None,
    source_title: str | None,
    source_url: str | None,
    inbox_path: Path,
    model: str,
    profile: LanguageProfile = DEFAULT_PROFILE,
    vocabulary_model: str = "Vocabulary",
    grammar_model: str = "Grammar",
) -> int:
    text = _read_analysis_text(text_argument, profile)
    source_title, source_url = _resolve_analysis_sources(source_title, source_url)
    inbox = load_or_create_inbox(inbox_path, profile)
    inbox_words = {normalize_headword(str(card["word"])) for card in inbox["cards"]}
    try:
        if (
            profile == DEFAULT_PROFILE
            and vocabulary_model == "Vocabulary"
            and grammar_model == "Grammar"
        ):
            known, anki_model = known_anki_headwords()
        else:
            known, anki_model = known_anki_headwords(profile, vocabulary_model, grammar_model)
    except (AnkiConnectError, OSError, RuntimeError) as exc:
        known, anki_model = set(), None
        print(f"Anki known-word check unavailable: {exc}")
    else:
        if anki_model:
            print(f"Checking known words in Anki note type: {anki_model}")
        else:
            print(f"Anki has no {profile.study_language} learning notes; skipping known words.")

    while True:
        analysis = (
            analyze_passage(text, model)
            if profile == DEFAULT_PROFILE
            else analyze_passage(text, model, profile)
        )
        _display_analysis_summary(analysis)
        if not analysis.candidates:
            print("\nNo worthwhile vocabulary or expressions were suggested.")
            return 0
        selected: list[int] = []
        retry = False
        for index, candidate in enumerate(analysis.candidates, start=1):
            _display_analysis_candidate(
                candidate, index, len(analysis.candidates), known, inbox_words, profile
            )
            while True:
                choice = (
                    input("Add this card? [y/N], [r]etry analysis, or [q]uit: ").strip().lower()
                )
                if choice in ("y", "yes"):
                    selected.append(index - 1)
                    break
                if choice in ("", "n", "no"):
                    break
                if choice == "r":
                    retry = True
                    break
                if choice == "q":
                    print("Cancelled. The inbox was not changed.")
                    return 0
                print("Choose y, n, r, or q.")
            if retry:
                break
        if retry:
            continue
        if not selected:
            print("No cards selected. The inbox was not changed.")
            return 0
        cards = []
        for index in selected:
            candidate = analysis.candidates[index]
            cards.append(
                {
                    "word": candidate.word,
                    "meaning": candidate.meaning,
                    "example_target": (
                        f"{candidate.example_vn}\n{candidate.everyday_example_vn}\n"
                        f"{candidate.simple_example_vn}"
                    ),
                    "example_native": (
                        f"{candidate.example_en}\n{candidate.everyday_example_en}\n"
                        f"{candidate.simple_example_en}"
                    ),
                    "tags": [
                        "source::analysis",
                        f"card_type::{candidate.card_type}",
                        profile.language_tag,
                        *candidate.tags,
                    ],
                    "ai_explanation": candidate.rationale,
                    "source_title": source_title,
                    "source_url": source_url,
                    "approved": True,
                    "skip": False,
                }
            )
        total = append_cards(inbox_path, cards, profile)
        print(f"Saved {len(cards)} cards to {inbox_path} (inbox total: {total}).")
        return 0


def _manual_tags() -> list[str]:
    tags: list[str] = []
    for prefix, label in (
        ("part_of_speech::", "part of speech"),
        ("topic::", "topic"),
        ("register::", "register"),
        ("level::", "level"),
    ):
        choices = sorted(tag for tag in ALLOWED_AI_TAGS if tag.startswith(prefix))
        tags.append(_choose(label, choices))
    return tags


def _choose_tags(
    card: dict[str, object], profile: LanguageProfile = DEFAULT_PROFILE
) -> tuple[list[str], str]:
    while True:
        method = input("Tags: [m]anual or [a]sk AI? [m]: ").strip().lower() or "m"
        if method == "m":
            return _manual_tags(), ""
        if method != "a":
            print("Choose m or a.")
            continue
        model = os.environ.get("OPENAI_MODEL", "gpt-5.6-sol")
        try:
            tags, explanation = suggest_card_tags(card, model, profile)
        except RuntimeError as exc:
            print(f"AI tagging unavailable: {exc}")
            print("Switching to manual tag selection.")
            return _manual_tags(), ""
        print(f"Suggested tags: {' '.join(tags)}")
        if explanation:
            print(f"Explanation: {explanation}")
        choice = input("[a]ccept, [r]etry AI, or [m]anual? [a]: ").strip().lower() or "a"
        if choice == "a":
            return tags, explanation
        if choice == "m":
            return _manual_tags(), ""


def _manual_image_url() -> dict[str, str]:
    url = input("Image URL (blank to skip): ").strip()
    return {
        "image_url": url,
        "image_source_url": "",
        "image_attribution": "",
        "image_license_url": "",
    }


def _empty_image() -> dict[str, str]:
    return {
        "image_url": "",
        "image_source_url": "",
        "image_attribution": "",
        "image_license_url": "",
    }


def _choose_image(default_query: str) -> dict[str, str]:
    if input("Search Wikimedia Commons for an image? [Y/n]: ").strip().lower() in ("n", "no"):
        return _manual_image_url()
    query = default_query
    while True:
        entered = input(f"Image search [{query}]: ").strip()
        query = entered or query
        try:
            images = search_commons(query)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            print(f"Commons search failed: {exc}")
            action = input("[r]etry, enter a manual [u]RL, or [s]kip? [r]: ").strip().lower() or "r"
            if action == "u":
                return _manual_image_url()
            if action == "s":
                return _empty_image()
            continue
        if not images:
            action = (
                input("No images found. [r]etry, manual [u]RL, or [s]kip? [r]: ").strip().lower()
                or "r"
            )
            if action == "u":
                return _manual_image_url()
            if action == "s":
                return _empty_image()
            continue
        try:
            open_gallery(images, query)
            print("Opened a browser gallery.")
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"Could not open the gallery: {exc}")
        for index, image in enumerate(images, start=1):
            print(f"  {index}. {image.title} — {image.attribution}")
            print(f"     {image.source_url}")
        while True:
            raw = (
                input(f"Choose 1-{len(images)}, [r]etry, manual [u]RL, or [s]kip: ").strip().lower()
            )
            if raw.isdigit() and 1 <= int(raw) <= len(images):
                return images[int(raw) - 1].card_fields()
            if raw == "r":
                break
            if raw == "u":
                return _manual_image_url()
            if raw == "s":
                return _empty_image()
            print("Choose an image number, r, u, or s.")


def _display_card(card: dict[str, object], profile: LanguageProfile = DEFAULT_PROFILE) -> None:
    print("\nCard preview")
    print(f"{profile.study_language}: {card['word']}")
    print(f"{profile.native_language}: {card['meaning']}")
    print(f"Example {profile.study_language}: {card.get('example_target', '')}")
    print(f"Example {profile.native_language}: {card.get('example_native', '')}")
    print(f"Tags:       {' '.join(card.get('tags', []))}")
    print(f"Image:      {card.get('image_source_url') or card.get('image_url') or '(none)'}")


def _choose_examples(
    word: str, meaning: str, profile: LanguageProfile = DEFAULT_PROFILE
) -> tuple[str, str]:
    while True:
        example_target = input(
            f"{profile.study_language} example (optional; type 'ai' to generate): "
        ).strip()
        if example_target.lower() != "ai":
            example_native = input(
                f"{profile.native_language} example translation (optional): "
            ).strip()
            return example_target, example_native
        try:
            model = os.environ.get("OPENAI_MODEL", "gpt-5.6-sol")
            if profile == DEFAULT_PROFILE:
                example_target, example_native = suggest_example_sentence(word, meaning, model)
            else:
                example_target, example_native = suggest_example_sentence(
                    word, meaning, model, profile
                )
        except RuntimeError as exc:
            print(f"AI sentence generation unavailable: {exc}")
            print("Enter an example manually, type 'ai' to retry, or leave it blank.")
            continue
        print(f"Generated {profile.study_language}: {example_target}")
        print(f"Generated {profile.native_language}: {example_native}")
        return example_target, example_native


def run_add(
    word: str | None,
    inbox_path: Path,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> int:
    word = word.strip() if word else ""
    word = word or _required_input(profile.study_language)
    meaning = _required_input(f"{profile.native_language} meaning")
    example_target, example_native = _choose_examples(word, meaning, profile)
    card: dict[str, object] = {
        "word": word,
        "meaning": meaning,
        "example_target": example_target,
        "example_native": example_native,
        "tags": [],
        "ai_explanation": "",
        "approved": True,
        "skip": False,
    }
    tags, explanation = (
        _choose_tags(card) if profile == DEFAULT_PROFILE else _choose_tags(card, profile)
    )
    card["tags"] = ["source::manual", "card_type::vocabulary", profile.language_tag, *tags]
    card["ai_explanation"] = explanation
    card.update(_choose_image(str(card["meaning"])))

    while True:
        _display_card(card, profile)
        choice = (
            input("[s]ave, [e]dit text, retag [t], change [i]mage, or [c]ancel? [s]: ")
            .strip()
            .lower()
            or "s"
        )
        if choice == "s":
            count = append_card(inbox_path, card, profile)
            print(f"Saved card {count} to {inbox_path}")
            return 0
        if choice == "c":
            print("Cancelled. The inbox was not changed.")
            return 0
        if choice == "e":
            card["word"] = _required_input(profile.study_language, str(card["word"]))
            card["meaning"] = _required_input(
                f"{profile.native_language} meaning", str(card["meaning"])
            )
            for key, label in (
                ("example_target", f"{profile.study_language} example"),
                ("example_native", f"{profile.native_language} translation"),
            ):
                current = str(card.get(key, ""))
                card[key] = input(f"{label} [{current}]: ").strip() or current
        elif choice == "t":
            tags, explanation = (
                _choose_tags(card) if profile == DEFAULT_PROFILE else _choose_tags(card, profile)
            )
            card["tags"] = [
                "source::manual", "card_type::vocabulary", profile.language_tag, *tags
            ]
            card["ai_explanation"] = explanation
        elif choice == "i":
            card.update(_choose_image(str(card["meaning"])))
        else:
            print("Choose s, e, t, i, or c.")


def _display_tone_family(family: ToneFamily) -> None:
    print(f"\nTone family: {family.base} (Southern Vietnamese)")
    print(" #  Tone     Form       Meaning / status")
    for index, entry in enumerate(family.entries, start=1):
        status = (
            entry.meaning if entry.common else entry.usage_note or "not a common standalone word"
        )
        marker = " " if entry.common else "×"
        print(f" {index}. {TONE_LABELS[entry.tone]:<8} {entry.form:<10} {marker} {status}")
        if entry.common:
            print(f"    {entry.example_vn} — {entry.example_en}")
    print("Note: Southern Vietnamese often merges hỏi and ngã in pronunciation.")


def _edit_tone_entry(family: ToneFamily) -> None:
    raw = input("Entry number to edit [1-6]: ").strip()
    if not raw.isdigit() or not 1 <= int(raw) <= len(family.entries):
        print("Enter a number from 1 to 6.")
        return
    entry = family.entries[int(raw) - 1]
    enabled = input(f"Create recall card for {entry.form}? [Y/n]: ").strip().lower()
    if enabled in {"n", "no"}:
        entry.common = False
    elif enabled in {"", "y", "yes"}:
        entry.common = True
    for sense_index, sense in enumerate(entry.senses, start=1):
        print(f"Sense {sense_index}")
        for attribute, label in (
            ("meaning", "English meaning"),
            ("part_of_speech", "Part of speech"),
            ("example_vn", "Vietnamese example"),
            ("example_en", "English example"),
        ):
            current = getattr(sense, attribute)
            value = input(f"{label} [{current}]: ").strip()
            if value:
                setattr(sense, attribute, value)
    value = input(f"Usage note [{entry.usage_note}]: ").strip()
    if value:
        entry.usage_note = value
    if entry.common and (
        not entry.senses
        or any(
            not all((sense.meaning, sense.part_of_speech, sense.example_vn, sense.example_en))
            for sense in entry.senses
        )
    ):
        raise ValueError(
            f"Enabled entry {entry.form!r} needs meanings, part of speech, and both examples."
        )


def _display_tone_actions(family: ToneFamily, existing: dict[str, dict[str, object]]) -> None:
    print("\nPlanned Anki changes")
    for entry in family.entries:
        if not entry.common:
            action = "recap only"
        elif entry.form in existing:
            action = "link existing Vocabulary note"
        else:
            action = "add new Vocabulary note"
        print(f"  {entry.form:<10} {action}")


def run_tones(
    syllable: str,
    output: Path | None,
    model: str,
    vocabulary_model: str,
    ai_model: str,
) -> int:
    base = normalize_syllable(syllable)
    family = generate_tone_family(base, ai_model)
    while True:
        _display_tone_family(family)
        choice = input("[s]ave, [e]dit, [r]egenerate, or [c]ancel? [s]: ").strip().lower() or "s"
        if choice == "s":
            break
        if choice == "c":
            print("Cancelled. No review file was written.")
            return 0
        if choice == "e":
            _edit_tone_entry(family)
        elif choice == "r":
            family = generate_tone_family(base, ai_model)
        else:
            print("Choose s, e, r, or c.")
    output = output or Path("reviews/tone-families") / f"{base}.review.json"
    review = tone_family_to_review(family, model, vocabulary_model)
    save_review_atomic(review, output)
    print(f"Saved tone family with {len(review['cards'])} Vocabulary cards: {output}")
    print(f"Import later with: ankii import {output}")
    return 0


def run_tone_import(
    family: ToneFamily,
    deck: str | None,
    model: str,
    vocabulary_model: str,
    review_path: Path | None = None,
) -> int:
    base = family.base
    decks = sorted(invoke("deckNames"), key=str.casefold)
    if deck is None:
        preferred = next((item for item in decks if "vietnamese" in item.casefold()), None)
        deck = _choose("deck", decks, preferred)
    elif deck not in decks:
        raise ValueError(f"Anki deck {deck!r} does not exist.")

    models = list(invoke("modelNames"))
    if vocabulary_model not in models:
        raise ValueError(
            f"Anki vocabulary note type {vocabulary_model!r} does not exist. "
            "Run 'ankii anki setup-note-types' first."
        )
    if model in models:
        duplicates = invoke("findNotes", query=f'note:"{model}" Base:"{base}"')
        if duplicates:
            raise ValueError(f"Tone family {base!r} already exists in note type {model!r}.")

    vocabulary_fields = set(invoke("modelFieldNames", modelName=vocabulary_model))
    vocabulary_mapping = infer_field_names(list(vocabulary_fields))
    for required in ("target", "native"):
        if vocabulary_mapping[required] not in vocabulary_fields:
            raise ValueError(
                f"Vocabulary note type {vocabulary_model!r} is missing a {required} field."
            )
    existing: dict[str, dict[str, object]] = {}
    for entry in family.entries:
        if not entry.common:
            continue
        field = vocabulary_mapping["target"]
        note_ids = invoke("findNotes", query=f'note:"{vocabulary_model}" "{field}:{entry.form}"')
        candidates = invoke("notesInfo", notes=note_ids) if note_ids else []
        exact = [
            note
            for note in candidates
            if unicodedata.normalize(
                "NFC",
                html.unescape(str(note.get("fields", {}).get(field, {}).get("value", ""))),
            ).strip()
            == entry.form
        ]
        if len(exact) > 1:
            raise ValueError(
                f"Vocabulary form {entry.form!r} matches multiple notes; resolve duplicates first."
            )
        if exact:
            existing[entry.form] = exact[0]

    new_entries = [entry for entry in family.entries if entry.common and entry.form not in existing]
    preflight_fields = vocabulary_fields | {VOCABULARY_LINK_FIELD}
    preflight_notes = [
        build_tone_vocabulary_note(entry, family, deck, vocabulary_model, preflight_fields, 1)
        for entry in new_entries
    ]
    if preflight_notes:
        check_notes = []
        for note in preflight_notes:
            check = {**note, "fields": dict(note["fields"])}
            if VOCABULARY_LINK_FIELD not in vocabulary_fields:
                check["fields"].pop(VOCABULARY_LINK_FIELD, None)
            check_notes.append(check)
        can_add = invoke("canAddNotes", notes=check_notes)
        if can_add != [True] * len(check_notes):
            raise ValueError("Anki rejected one or more generated Vocabulary notes.")

    _display_tone_actions(family, existing)
    print(
        f"\nReady: 1 {model} recap, {len(new_entries)} new {vocabulary_model} notes, "
        f"{len(existing)} existing {vocabulary_model} notes linked in {deck!r}."
    )
    if input("Type IMPORT to continue: ").strip() != "IMPORT":
        print("Cancelled. Anki was not changed.")
        return 0

    created_ids: list[int] = []
    updated_existing: list[tuple[int, str, list[str]]] = []
    try:
        created = setup_tone_family_model(model)
        setup_vocabulary_tone_link(vocabulary_model)
        family_note = build_tone_family_note(family, deck, model)
        parent_id = invoke("addNote", request_timeout=180, note=family_note)
        if not isinstance(parent_id, int):
            raise RuntimeError("AnkiConnect did not return the ToneFamily note ID.")
        created_ids.append(parent_id)

        final_fields = vocabulary_fields | {VOCABULARY_LINK_FIELD}
        new_notes = [
            build_tone_vocabulary_note(
                entry, family, deck, vocabulary_model, final_fields, parent_id
            )
            for entry in new_entries
        ]
        if new_notes:
            results = invoke("addNotes", request_timeout=180, notes=new_notes)
            if not isinstance(results, list) or len(results) != len(new_notes):
                raise RuntimeError("AnkiConnect returned invalid Vocabulary add results.")
            created_ids.extend(note_id for note_id in results if isinstance(note_id, int))
            if any(not isinstance(note_id, int) for note_id in results):
                raise RuntimeError("Anki failed to add one or more Vocabulary notes.")

        family_tags = ["source::openai", "dialect::southern", f"tone_family::{base}"]
        for entry in family.entries:
            if entry.form not in existing:
                continue
            note = existing[entry.form]
            note_id = int(note["noteId"])
            old_field = str(note.get("fields", {}).get(VOCABULARY_LINK_FIELD, {}).get("value", ""))
            old_tags = list(note.get("tags", []))
            added_tags = [tag for tag in family_tags if tag not in old_tags]
            updated_existing.append((note_id, old_field, added_tags))
            invoke(
                "updateNoteFields",
                note={
                    "id": note_id,
                    "fields": {VOCABULARY_LINK_FIELD: tone_family_link(base, parent_id)},
                },
            )
            if added_tags:
                invoke("addTags", notes=[note_id], tags=" ".join(added_tags))
    except Exception as exc:
        rollback_errors = []
        for note_id, old_field, added_tags in reversed(updated_existing):
            try:
                invoke(
                    "updateNoteFields",
                    note={"id": note_id, "fields": {VOCABULARY_LINK_FIELD: old_field}},
                )
                if added_tags:
                    invoke("removeTags", notes=[note_id], tags=" ".join(added_tags))
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        if created_ids:
            try:
                invoke("deleteNotes", notes=created_ids)
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        if rollback_errors:
            raise RuntimeError(f"{exc} Rollback also failed: {'; '.join(rollback_errors)}") from exc
        raise
    action = "Created" if created else "Updated"
    print(
        f"{action} {model!r}; added recap note {parent_id}, {len(new_entries)} Vocabulary "
        f"notes, and linked {len(existing)} existing notes."
    )
    if review_path is not None:
        archive_path = archive_completed_review(review_path)
        if archive_path is not None:
            print(f"Archived: {archive_path}")
    return 0


def _has_ai_tags(card: dict[str, object]) -> bool:
    ai_tags = [
        tag
        for tag in card.get("tags", [])
        if isinstance(tag, str) and tag.startswith(AI_TAG_PREFIXES)
    ]
    return has_complete_ai_taxonomy(ai_tags)


def run_wizard(
    lesson_value: str | None,
    profile: LanguageProfile = DEFAULT_PROFILE,
    vocabulary_model: str = "Vocabulary",
    grammar_model: str = "Grammar",
) -> int:
    lesson_value = lesson_value or input("YourHomework lesson ID or URL: ").strip()
    if not lesson_value:
        raise ValueError("A lesson ID or URL is required.")

    lesson = fetch_lesson(lesson_value)
    review_path = profile.review_root / f"{lesson.public_id}.review.json"
    if review_path.exists():
        print(f"Using existing review: {review_path}")
    else:
        save_review(create_review(lesson, profile), review_path)
        print(f"Created review with {len(lesson.items)} cards: {review_path}")

    review = load_review(review_path)
    untagged = sum(not _has_ai_tags(card) for card in review["cards"])
    if untagged:
        api_key, key_source = get_openai_api_key()
        if api_key:
            print(f"OpenAI API key found in {key_source}.")
            answer = input(f"Tag {untagged} cards with OpenAI now? [Y/n]: ").strip().lower()
            if answer in ("", "y", "yes"):
                count = tag_review(
                    review_path,
                    os.environ.get("OPENAI_MODEL", "gpt-5.6-sol"),
                    profile,
                )
                print(f"Tagged {count} cards.")
        else:
            print(
                "\nThis review has untagged cards. To use Codex without an API key, ask:\n"
                f"  Tag every card in {review_path.resolve()} using the project taxonomy.\n"
                "Then run this wizard again. You may also continue without AI tags."
            )
            answer = input("Continue without AI tags? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                print("Stopped before approval or import. The review file was preserved.")
                return 0

    review = load_review(review_path)
    pending = sum(not card["approved"] and not card["skip"] for card in review["cards"])
    if pending:
        print(f"\n{pending} cards still need review.")
        run_approve(review_path, profile)

    review = load_review(review_path)
    approved = sum(card["approved"] and not card["skip"] for card in review["cards"])
    if not approved:
        print("No cards are approved. Stopped without contacting Anki.")
        return 0
    print(f"\nApproved cards ready for Anki: {approved}")

    model = vocabulary_model
    available_fields = invoke("modelFieldNames", modelName=model)
    field_names = infer_field_names(available_fields)
    print("\nAutomatic field mapping:")
    for key, field in field_names.items():
        if field in available_fields:
            print(f"  {key.replace('_', ' '):12} -> {field}")

    args = argparse.Namespace(
        review_file=review_path,
        deck=profile.deck,
        model=model,
        grammar_model=grammar_model,
        **{f"field_{key}": value for key, value in field_names.items()},
    )
    return run_import(args, profile)


def run_import(
    args: argparse.Namespace, profile: LanguageProfile = DEFAULT_PROFILE
) -> int:
    _resolve_import_destination(args, profile)
    loaded_review = load_review(args.review_file) if args.review_file.exists() else {}
    if loaded_review:
        validate_review_profile(loaded_review, profile)
    if loaded_review.get("review_kind") == "tone_family":
        family = tone_family_from_review(loaded_review)
        metadata = loaded_review["tone_family"]
        tone_model = getattr(args, "tone_model", None) or str(
            metadata.get("tone_model", "ToneFamily")
        )
        vocabulary_model = args.model
        if vocabulary_model == "Vocabulary" and metadata.get("vocabulary_model"):
            vocabulary_model = str(metadata["vocabulary_model"])
        return run_tone_import(
            family,
            args.deck,
            tone_model,
            vocabulary_model,
            args.review_file,
        )
    legacy_field_names = {
        "target": getattr(args, "field_vietnamese", None),
        "native": getattr(args, "field_english", None),
        "example_target": getattr(args, "field_example_vn", None),
        "example_native": getattr(args, "field_example_en", None),
        **{
            key: getattr(args, f"field_{key}", None)
            for key in ("source", "lesson", "explanation", "image", "import_id")
        },
    }
    configured_fields = {
        key: getattr(args, f"field_{key}", None) or legacy_field_names.get(key)
        for key in GENERIC_FIELD_DEFAULTS
    }
    if any(value is None for value in configured_fields.values()):
        available_fields = invoke("modelFieldNames", modelName=args.model)
        inferred_fields = infer_field_names(available_fields)
    else:
        inferred_fields = GENERIC_FIELD_DEFAULTS
    field_names = {
        key: configured_fields[key] or inferred_fields[key] for key in GENERIC_FIELD_DEFAULTS
    }
    review, notes, can_add = prepare_import(
        args.review_file,
        args.deck,
        args.model,
        field_names,
        getattr(args, "grammar_model", None) or "Grammar",
    )
    ready = [note for note, allowed in zip(notes, can_add, strict=True) if allowed]
    blocked = len(notes) - len(ready)
    skipped = sum(1 for card in review["cards"] if card["skip"])
    note_type_counts = Counter(str(note.get("modelName", args.model)) for note in notes)

    print(f"Destination deck: {args.deck}")
    print("Note types detected:")
    for note_type, count in note_type_counts.items():
        print(f"  {note_type}: {count}")
    print(f"Ready to import:  {len(ready)}")
    print(f"Blocked/duplicate:{blocked:>3}")
    print(f"Skipped:          {skipped}")
    if not ready:
        print("Nothing to import; all approved cards already exist or are blocked by Anki.")
        archive_path = archive_completed_review(args.review_file)
        if archive_path is not None:
            print(f"Archived: {archive_path}")
        return 0

    confirmation = input("\nType IMPORT to continue: ").strip()
    if confirmation != "IMPORT":
        print("Import cancelled. No notes were added.")
        return 0

    result = add_notes(ready)
    added = sum(note_id is not None for note_id in result)
    failed = len(result) - added
    print(f"Added:  {added}")
    print(f"Failed: {failed}")
    approved_entries = [
        (index, card)
        for index, card in enumerate(review["cards"])
        if card["approved"] and not card["skip"]
    ]
    ready_entries = [
        entry for entry, allowed in zip(approved_entries, can_add, strict=True) if allowed
    ]
    imported = [
        (entry[0], note_id)
        for entry, note_id in zip(ready_entries, result, strict=True)
        if note_id is not None
    ]
    archive_path = archive_imported_cards(
        args.review_file,
        review,
        imported,
        args.deck,
        args.model,
    )
    if archive_path is not None:
        print(f"Archived: {archive_path}")
        remaining = len(review["cards"]) - len(imported)
        print(f"Inbox remaining: {remaining}")
    elif failed == 0:
        archive_path = archive_completed_review(args.review_file)
        if archive_path is not None:
            print(f"Archived: {archive_path}")
    return 0 if failed == 0 else 1


def run_backfill(
    review_file: Path, model: str, profile: LanguageProfile = DEFAULT_PROFILE
) -> int:
    print(
        "This fills only empty Example Target/Example Native fields on notes matching both "
        f"the review's source lesson and {profile.study_language} word. Existing values are "
        "preserved."
    )
    if input("Type BACKFILL to continue: ").strip() != "BACKFILL":
        print("Backfill cancelled. No notes were changed.")
        return 0
    result = backfill_examples(review_file, model)
    print(f"Review cards:    {result['review_cards']}")
    print(f"Notes matched:   {result['notes_matched']}")
    print(f"Notes updated:   {result['notes_updated']}")
    print(f"Ambiguous words: {result['ambiguous_words']}")
    return 0


def run_retag(
    model: str, ai_model: str, profile: LanguageProfile = DEFAULT_PROFILE
) -> int:
    changes = retag_notes(model, ai_model, profile)
    changed = sum(item["old_tags"] != item["new_tags"] for item in changes)
    print(f"Notes found:       {len(changes)}")
    print(f"Tags would change: {changed}")
    if not changed:
        print("Nothing to update.")
        return 0
    if input("\nType RETAG to update Anki: ").strip() != "RETAG":
        print("Retag cancelled. No notes were changed.")
        return 0
    print(f"Notes updated: {apply_retags(changes)}")
    return 0


def run_reimport_all(reviews: Path, model: str, deck: str) -> int:
    changes, stats = prepare_reimport(reviews, model, deck)
    print(f"Review files:    {stats['files']}")
    print(f"Review cards:    {stats['cards']}")
    print(f"Unique matches:  {stats['matched']}")
    print(f"Missing notes:   {stats['missing']}")
    print(f"Ambiguous notes: {stats['ambiguous']}")
    if not changes:
        print("Nothing can be updated safely.")
        return 0
    if input("\nType REIMPORT to update Anki: ").strip() != "REIMPORT":
        print("Reimport cancelled. No notes were changed.")
        return 0
    print(f"Notes updated: {apply_reimport(changes)}")
    return 0


def _parse_grammar_actions(value: str, count: int) -> tuple[list[int], list[int]]:
    create: set[int] = set()
    reject: set[int] = set()
    for raw in value.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        destination = reject if token.startswith("x") else create
        token = token[1:] if token.startswith("x") else token
        if "-" in token:
            parts = token.split("-", 1)
            if not all(part.isdigit() for part in parts):
                raise ValueError("Use selections such as 1,3-5 and rejections such as x2,x6-8.")
            start, end = (int(part) for part in parts)
            if start > end:
                raise ValueError("Selection ranges must be ascending.")
            destination.update(range(start, end + 1))
        elif token.isdigit():
            destination.add(int(token))
        else:
            raise ValueError("Use selections such as 1,3-5 and rejections such as x2,x6-8.")
    if any(index < 1 or index > count for index in create | reject):
        raise ValueError(f"Choose grammar suggestions from 1 to {count}.")
    if create & reject:
        raise ValueError("A suggestion cannot be both created and rejected.")
    return sorted(index - 1 for index in create), sorted(index - 1 for index in reject)


def _display_grammar_suggestions(suggestions: list[GrammarSuggestion]) -> None:
    for index, item in enumerate(suggestions, start=1):
        print(f"\n{index}. {item.pattern} — {item.explanation}")
        print(f"   From {item.source_word} (Vocabulary note {item.source_note_id})")
        print(f"   Source:   {item.example_vn} — {item.example_en}")
        print(f"   Everyday: {item.everyday_example_vn} — {item.everyday_example_en}")


def run_grammar_check(
    vocabulary_model: str,
    grammar_model: str,
    deck: str,
    ai_model: str,
    ignore_file: Path,
    profile: LanguageProfile = DEFAULT_PROFILE,
) -> int:
    models = invoke("modelNames")
    for model in (vocabulary_model, grammar_model):
        if model not in models:
            raise ValueError(
                f"Anki note type {model!r} does not exist. "
                "Run 'ankii anki setup-note-types' first."
            )
    decks = sorted(invoke("deckNames"), key=str.casefold)
    if deck not in decks:
        raise ValueError(f"Anki deck {deck!r} does not exist.")

    ignored = load_ignored(ignore_file)
    while True:
        suggestions, stats = discover_grammar(
            vocabulary_model,
            grammar_model,
            ai_model,
            set(ignored),
            profile,
        )
        print(f"Vocabulary notes: {stats['notes']}")
        print(f"Notes analyzed:   {stats['analyzed']}")
        print(f"Notes skipped:    {stats['skipped']}")
        print(f"New suggestions:  {stats['suggestions']}")
        if not suggestions:
            print("No missing grammar structures were found.")
            return 0
        _display_grammar_suggestions(suggestions)
        while True:
            choice = (
                input("\nCreate with 1,3-5; reject with x2,x6-8; [r]escan; or [c]ancel: ")
                .strip()
                .lower()
            )
            if choice == "c":
                print("Cancelled. Anki and the ignore list were not changed.")
                return 0
            if choice == "r":
                break
            try:
                create_indexes, reject_indexes = _parse_grammar_actions(choice, len(suggestions))
            except ValueError as exc:
                print(exc)
                continue
            if not create_indexes and not reject_indexes:
                print("Every suggestion was deferred. Nothing was changed.")
                return 0

            selected = [suggestions[index] for index in create_indexes]
            rejected = [suggestions[index] for index in reject_indexes]
            notes = []
            for item in selected:
                card = {
                    "import_id": new_import_id(),
                    "word": item.pattern,
                    "meaning": item.explanation,
                    "example_target": f"{item.example_vn}\n{item.everyday_example_vn}",
                    "example_native": f"{item.example_en}\n{item.everyday_example_en}",
                    "source_url": item.source,
                    "tags": [
                        "source::grammar-check",
                        "card_type::grammar",
                        profile.language_tag,
                        f"derived_from_note::{item.source_note_id}",
                        *item.tags,
                    ],
                    "ai_explanation": f"Derived from Vocabulary: {item.source_word}",
                }
                notes.append(build_grammar_note(card, {}, deck, grammar_model))
            can_add = invoke("canAddNotes", notes=notes) if notes else []
            if not isinstance(can_add, list) or len(can_add) != len(notes):
                raise RuntimeError("AnkiConnect returned an invalid duplicate-check response.")
            ready = [note for note, allowed in zip(notes, can_add, strict=True) if allowed]
            blocked = len(notes) - len(ready)
            print(f"\nGrammar cards ready: {len(ready)}")
            print(f"Blocked/duplicate:   {blocked}")
            print(f"Patterns to reject:  {len(rejected)}")
            if input("Type APPLY to continue: ").strip() != "APPLY":
                print("Cancelled. Anki and the ignore list were not changed.")
                return 0
            results = add_notes(ready) if ready else []
            added = sum(note_id is not None for note_id in results)
            failed = len(results) - added
            if rejected:
                ignored = add_rejections(ignored, rejected)
                save_ignored(ignore_file, ignored)
            print(f"Grammar cards added: {added}")
            print(f"Grammar cards failed: {failed}")
            print(f"Patterns rejected: {len(rejected)}")
            return 0 if failed == 0 else 1
        # Rescan requested; no write has occurred.


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command is None:
            from ankii.tui import run_tui

            raise SystemExit(run_tui(args.settings, args.profile))
        if args.command == "setup":
            raise SystemExit(run_setup(args.settings, skip_key=args.skip_key))
        if args.command == "key":
            raise SystemExit(run_key(args.key_command))
        if args.command == "profile":
            raise SystemExit(run_profile(args, args.settings))
        settings = load_settings(args.settings)
        profile = settings.select_profile(args.profile)
        if getattr(args, "deck", None) is not None:
            raise ValueError(
                "--deck is not supported; the active profile's configured deck is enforced."
            )
        if args.command in {"tones", "yhw"} and not profile.is_vietnamese:
            raise ValueError(
                f"{args.command!r} is available only for a Vietnamese study profile; "
                f"active profile {profile.name!r} studies {profile.study_language}."
            )
        if (
            getattr(args, "model", None) is None
            and args.command in {"import", "retag", "reimport", "grammar-check"}
        ) or (args.command == "import" and args.model == "Vocabulary"):
            args.model = settings.vocabulary_model
        if getattr(args, "grammar_model", None) is None or (
            args.command == "import" and args.grammar_model == "Grammar"
        ):
            args.grammar_model = settings.grammar_model
        if args.command == "add":
            exit_code = run_add(args.word, args.inbox or profile.inbox_path, profile)
        elif args.command == "tones":
            exit_code = run_tones(
                args.syllable,
                args.output
                or profile.review_root / "tone-families" / f"{args.syllable}.review.json",
                args.model,
                args.vocabulary_model,
                args.ai_model,
            )
        elif args.command == "analyze":
            exit_code = run_analyze(
                args.text,
                args.source_title,
                args.source_url,
                args.inbox or profile.inbox_path,
                args.model,
                profile,
                settings.vocabulary_model,
                settings.grammar_model,
            )
        elif args.command == "yhw" and args.yhw_command == "fetch":
            exit_code = run_fetch(args.lesson, args.output)
        elif args.command == "yhw" and args.yhw_command == "review":
            exit_code = run_review(args.lesson, args.output, profile)
        elif args.command == "tag":
            count = tag_review(args.review_file, args.model, profile)
            print(f"Tagged {count} cards in {args.review_file} using {args.model}.")
            exit_code = 0
        elif args.command == "approve":
            exit_code = run_approve(_resolve_approve_file(args.review_file, profile), profile)
        elif args.command == "yhw" and args.yhw_command == "wizard":
            exit_code = run_wizard(
                args.lesson, profile, settings.vocabulary_model, settings.grammar_model
            )
        elif args.command == "anki":
            selected_model = getattr(args, "model", None) or getattr(args, "source", None)
            exit_code = run_anki(
                args.anki_command,
                selected_model,
                profile,
                settings.vocabulary_model,
                settings.grammar_model,
            )
        elif args.command == "import":
            exit_code = run_import(args, profile)
        elif args.command == "backfill-examples":
            exit_code = run_backfill(args.review_file, args.model, profile)
        elif args.command == "retag":
            exit_code = run_retag(args.model, args.ai_model, profile)
        elif args.command == "reimport":
            reviews, model, deck = _resolve_reimport_options(
                args.reviews or profile.review_root, args.model, profile
            )
            exit_code = run_reimport_all(reviews, model, deck)
        elif args.command == "grammar-check":
            exit_code = run_grammar_check(
                args.model,
                args.grammar_model,
                profile.deck,
                args.ai_model,
                args.ignore_file or profile.grammar_ignore_path,
                profile,
            )
        else:
            parser.error(f"Unknown command: {args.command}")
            return
    except (AnkiConnectError, OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled. No pending Anki write was performed.", file=sys.stderr)
        raise SystemExit(130) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
