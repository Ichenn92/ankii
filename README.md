# ankii

Fetch a public YourHomework vocabulary lesson, review and tag it locally, then import
approved cards into Anki through AnkiConnect. The same installation supports multiple
studied languages.

> [!IMPORTANT]
> ankii is an unofficial community project. It is not affiliated with, endorsed by,
> or sponsored by Anki, AnkiConnect, YourHomework, Wikimedia, or OpenAI. Users are
> responsible for respecting the rights and terms that apply to material they import.

## Install

ankii is a Python 3.11+ command-line application. For local development:

```bash
git clone https://github.com/Ichenn92/ankii.git
cd ankii
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[ai,dev]"
```

For an isolated user installation after the public repository exists:

```bash
brew install pipx
pipx ensurepath
pipx install "ankii[ai] @ git+https://github.com/Ichenn92/ankii.git@main"
```

Install the AnkiConnect add-on in Anki Desktop and keep Anki open for commands that
read or change the Anki collection.

## Terminal interface

Run `ankii` without a subcommand to open the full-screen terminal interface:

```bash
ankii
```

Choose actions with the arrow keys and Enter, or use the displayed shortcut keys. Each workflow
opens in an embedded interactive console, including its prompts and safety confirmations. Press
Escape after it finishes to return to the dashboard, `p` to switch profiles, and `q` to quit. All
individual commands remain available for scripting and direct use.

## First-time setup

Run the guided setup once:

```bash
ankii setup
```

It creates a per-user `anki.toml`, local review directories, and offers to store an
OpenAI API key in macOS Keychain. The key is entered through the macOS Keychain prompt;
it is not written to the repository, configuration file, or shell history.

Default data locations are:

| Platform | Directory |
| --- | --- |
| macOS | `~/Library/Application Support/ankii` |
| Linux | `${XDG_DATA_HOME:-~/.local/share}/ankii` |
| Windows | `%LOCALAPPDATA%\ankii` |

Set `ANKII_HOME` to use a different directory. Generated reviews, archives,
downloaded lesson JSON, the grammar ignore list, and settings stay under this private
data directory. They are not part of the source repository.

Key management remains available separately:

```bash
ankii key set
ankii key status
ankii key delete
```

`OPENAI_API_KEY` is also supported and takes precedence over Keychain. AI features use
`OPENAI_MODEL` when set.

## Configuration and profiles

Setup creates Vietnamese and French starter profiles. Edit the generated `anki.toml`
to change decks, languages, models, or analysis levels. A reference copy is available
at [`anki.example.toml`](anki.example.toml).

```toml
settings_version = 1
default_profile = "vietnamese"

[anki]
vocabulary_model = "Vocabulary"
grammar_model = "Grammar"

[profiles.french]
study_language = "French"
native_language = "English"
deck = "French"
analysis_min_level = "A1"
analysis_max_level = "B2"
```

Select a profile for one command or a shell session:

```bash
ankii --profile french add "bonjour"
ANKI_PROFILE=french ankii analyze
```

Selection precedence is `--profile`, then `ANKI_PROFILE`, then `default_profile`.
Each profile has its own review directory and one enforced Anki deck.

## Common workflows

Add a word manually:

```bash
ankii add
ankii add "xin chào"
```

Analyze a passage and choose suggested vocabulary or grammar cards:

```bash
ankii analyze --source-title "Book or article" --source-url "https://example.com/source"
```

Fetch, review, tag, approve, and import a public YourHomework lesson with the guided
workflow:

```bash
ankii yhw wizard 313789981
```

You can supply a complete YourHomework URL or omit the ID to be prompted. Individual
steps are also available:

```bash
ankii yhw fetch 313789981
ankii yhw review 313789981
ankii tag /path/to/313789981.review.json
ankii approve
ankii import
```

`yhw fetch` stores raw downloads under the private data directory by default. Review
and wizard commands store review JSON under the active profile. Explicit `--output`,
`--inbox`, `--reviews`, and review-file arguments remain available.

Learn Southern Vietnamese tone families:

```bash
ankii tones ma
ankii import
```

Inspect Anki and set up the shared note types:

```bash
ankii anki status
ankii anki decks
ankii anki models
ankii anki fields Vocabulary
ankii anki setup-note-types Vietnamese
```

Maintenance commands preview their changes and require explicit confirmation:

```bash
ankii grammar-check --all --model Vocabulary --grammar-model Grammar
ankii retag --all --model Vocabulary
ankii reimport --all --model Vocabulary
```

Import uses AnkiConnect's duplicate check before writing and requires the exact
confirmation `IMPORT`. Retagging and reimporting require `RETAG` and `REIMPORT`.

## Privacy and content

Review files can contain study history, source titles and URLs, generated explanations,
and Anki note identifiers. Keep them in the per-user data directory and do not commit
them. The repository ignores `reviews/`, `anki.toml`, `.env`, downloads, exports, and
temporary files.

Only synthetic demonstration data belongs in `examples/`. Do not contribute copied
lessons, course material, song lyrics, personal review archives, credentials, or Anki
collection data.

Wikimedia Commons selections retain source, attribution, and license URLs in the local
review data. Verify that any imported media is suitable for your intended use.

## Development

```bash
python -m pip install -e ".[ai,dev]"
pytest
ruff check .
```

The installed command is `ankii`, matching the project and avoiding conflicts with Anki's
own executable on systems where it is available on `PATH`.

## License

The software is released under the [MIT License](LICENSE). Imported or linked content
is not covered by the project's MIT license.
