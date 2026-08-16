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

## Update

Install updates from the public repository with:

```bash
pipx upgrade ankii
```

`pipx` remembers the Git source used during installation. If a release needs to be
downloaded again, including one published without a version change, use:

```bash
pipx reinstall ankii
```

Updating the application does not remove settings, downloaded lessons, or reviews
stored in the private per-user data directory described below.

Install the AnkiConnect add-on in Anki Desktop and keep Anki open for commands that
read or change the Anki collection.

## Terminal interface

Run `ankii` without a subcommand to open the full-screen terminal interface:

```bash
ankii
```

Check the installed version against GitHub, or upgrade the pipx installation explicitly:

```bash
ankii version
ankii upgrade
```

Launching the terminal interface does not perform a network check.

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

Audio is opt-in per profile. This example generates one MP3 for the target word and one MP3
containing all target-language example lines during import:

```bash
ankii audio setup
```

The guided command updates the active profile in `anki.toml` and prompts for the speech model,
voice, accent preference, and additional instructions. The same values can be supplied with
`--enable`, `--model`, `--voice`, `--accent`, and `--instructions` for scripting.

```toml
[profiles.vietnamese.audio]
enabled = true
provider = "openai"
model = "gpt-4o-mini-tts"
voice = "marin"
language = ""
accent = "Southern Vietnamese (Saigon)"
instructions = "Speak clearly at a natural, learner-friendly pace."
```

To generate audio offline with a voice installed on this Mac, list the available voices and
then run setup:

```bash
ankii audio voices --language Vietnamese
ankii audio setup --enable --provider local
```

Local setup stores `provider = "local"`, `model = "macos-say"`, the selected voice, and its
locale (for example `language = "vi_VN"`) in the profile's audio table. Generation uses the
macOS `say` command and local `ffmpeg`; no study text is sent to OpenAI. Clips use the same
deterministic MP3 cache and Anki fields as OpenAI-generated audio.

Run `ankii anki setup-note-types` after enabling audio so Vocabulary has `Target Audio` and
`Example Audio` fields. Audio generation begins only after the `IMPORT` confirmation and only
for non-duplicate Vocabulary notes. MP3 files are cached under the active profile's `audio/`
directory; changing the text, model, voice, accent, or instructions creates a new cache entry.
OpenAI API charges apply. The voices are AI-generated and built-in voices are optimized for
English, so verify regional pronunciation such as Southern Vietnamese by listening.

Note-type setup also disables automatic audio playback for the active profile's deck while
retaining Anki's replay controls. The target control is displayed beside the target text, and
example controls are displayed inside the example box. Run setup again to migrate existing
Vocabulary templates to this layout.

To add audio to Vocabulary notes that already exist in Anki, run:

```bash
ankii backfill-audio
```

The command finds missing target-word and combined-example clips in the active profile's deck
and asks for each one: `y` generates or reuses the cached clip, while `n` permanently suppresses
that clip. Each audio field contains at most one sound reference. Any existing sound counts as
complete even if the provider, model, language, voice, accent, or instructions later change.
Declines are saved in the profile's `audio-skip.json`, so later runs do not ask again. For an
empty field, changing the speech configuration makes a previously declined rendition eligible
for review again.

Select a profile for one command or a shell session:

```bash
ankii --profile french add "bonjour"
ANKI_PROFILE=french ankii analyze
```

Create a profile interactively, or provide every value directly:

```bash
ankii profile create
ankii profile create spanish --study-language Spanish --native-language English \
  --deck Spanish --min-level A1 --max-level B2 --default
```

Interactive creation selects study and native languages from a validated list. Direct language
flags are case-insensitive and reject unknown spellings. Omit the profile name to derive it from
the study language automatically:

```bash
ankii profile languages
ankii profile create --study-language Spanish --native-language English --deck Spanish
# Creates the profile "spanish"
```

Set any existing profile as the default:

```bash
ankii profile default
ankii profile default spanish
```

List profiles or delete one. Deletion preserves its review and archive files:

```bash
ankii profile list
ankii profile delete spanish
ankii profile delete spanish --yes
ankii profile delete vietnamese --new-default spanish --yes
```

Deleting the current default requires a replacement profile. Without `--yes`, deletion asks you
to type `DELETE` as confirmation. All profile actions are also available from the terminal
dashboard.

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

You can supply a complete YourHomework URL or omit the ID to be prompted. The wizard
stores review JSON under the active profile and resumes an existing review when run again.
Explicit `--inbox`, `--reviews`, and review-file arguments remain available to the
general review commands.

Inspect Anki and set up the shared note types:

```bash
ankii anki status
ankii anki decks
ankii anki models
ankii anki fields Vocabulary
ankii anki bootstrap-note-types
ankii anki setup-note-types Vietnamese
```

Use `bootstrap-note-types` for a new Anki collection. It creates the shared `Vocabulary`
and `Grammar` note types without requiring a language-specific source note type and leaves
either model untouched when it already exists. Use `setup-note-types SOURCE` when migrating
an existing language-specific vocabulary note type instead.

The shared note types use language-neutral fields: `Target`, `Native`, `Example Target`,
`Example Native`, `Target Audio`, `Example Audio`, and the optional `Related Words`. `Source`
remains reserved for citation titles and URLs. Setup migrates values from legacy `Vietnamese`,
`English`, `Example VN`, and `Example EN` fields before removing those language-specific fields.

Maintenance commands preview their changes and require explicit confirmation:

```bash
ankii retag --all --model Vocabulary
ankii reimport --all --model Vocabulary
```

Import uses AnkiConnect's duplicate check before writing and requires the exact
confirmation `IMPORT`. Retagging and reimporting require `RETAG` and `REIMPORT`.

## Privacy and content

Review files can contain study history, source titles and URLs, generated explanations,
cached AI-generated speech, and Anki note identifiers. Text sent for speech generation is
processed by the configured provider. Keep these files in the per-user data directory and do
not commit them. The repository ignores `reviews/`, `anki.toml`, `.env`, downloads, exports,
and temporary files.

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

### Manual release

Choose the smallest appropriate [Semantic Versioning](https://semver.org/) increment: a
patch for a compatible fix, a minor version for a backward-compatible feature, and a major
version for a breaking change. Before `1.0.0`, use a minor version for breaking pre-stable
changes. The example below releases `0.2.0`; substitute the intended version throughout.

1. Start from `main`, inspect the worktree, and fetch the latest branch and tags:

   ```bash
   git switch main
   git status --short
   git diff
   git fetch origin main --tags
   git merge --ff-only origin/main
   git tag --list v0.2.0
   git ls-remote --exit-code --tags origin refs/tags/v0.2.0
   ```

   The final two commands must not find an existing `v0.2.0` tag. `git ls-remote` exits with
   status 2 when the remote tag is absent, which is expected here. Stop if the worktree
   contains unrelated changes or `main` cannot be fast-forwarded.

2. Set `project.version` in `pyproject.toml` and `__version__` in
   `src/ankii/__init__.py` to the same version. Update the README as needed when commands,
   configuration, installation, or behavior changed.

3. Run the source checks from the repository root:

   ```bash
   PYTHONPATH=src .venv/bin/python -m pytest -q
   .venv/bin/ruff check .
   git diff --check
   ```

4. Build and smoke-test the distributable package, not only the source checkout. Install
   `build` first if it is not already available (`.venv/bin/python -m pip install build`).

   ```bash
   .venv/bin/python -m build
   ANKII_SMOKE_DIR="$(mktemp -d)"
   python3 -m venv "$ANKII_SMOKE_DIR"
   "$ANKII_SMOKE_DIR/bin/python" -m pip install dist/ankii-0.2.0-py3-none-any.whl
   "$ANKII_SMOKE_DIR/bin/ankii" --help
   rm -rf "$ANKII_SMOKE_DIR"
   ```

5. Review the complete diff, stage only release files, and create the release commit:

   ```bash
   git status --short
   git diff
   git add pyproject.toml src/ankii/__init__.py
   git diff --cached
   git commit -m "Release 0.2.0"
   ```

   Add any other files that intentionally belong to the release, but never stage local
   configuration, credentials, review data, or unrelated changes.

6. Confirm the commit is on `main`, create an annotated tag on that exact commit, and verify
   it:

   ```bash
   git branch --show-current
   git merge-base --is-ancestor origin/main HEAD
   git tag -a v0.2.0 -m "Release 0.2.0"
   git rev-parse HEAD
   git rev-list -n 1 v0.2.0
   git status --short
   ```

   The two commit hashes must match, and no release changes should remain unstaged.

7. Publish `main` first, followed by only the new tag:

   ```bash
   git push origin main
   git push origin v0.2.0
   ```

   Do not use `git push --tags`. Creating a GitHub release or publishing to a package index is
   separate and should only be done intentionally. The repository-local `ankii-release` skill
   follows this same checklist automatically.

The installed command is `ankii`, matching the project and avoiding conflicts with Anki's
own executable on systems where it is available on `PATH`.

## License

The software is released under the [MIT License](LICENSE). Imported or linked content
is not covered by the project's MIT license.
