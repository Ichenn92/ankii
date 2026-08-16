---
name: ankii-release
description: Prepare and finalize versioned ankii updates with synchronized package versions, verification, a release commit, and an annotated Git tag. Use when completing, releasing, publishing, shipping, or tagging an ankii update, or when the user asks to bump the version or prepare the repository for pipx upgrades.
---

# ankii release

Apply this workflow to every releaseable ankii update. Do not create a tag for unfinished work.

## Prepare the release

1. Inspect `git status`, the complete diff, the current branch, remotes, and existing local and remote tags. Preserve unrelated user changes and never stage secrets or private study data.
2. Confirm that `project.version` in `pyproject.toml` and `__version__` in `src/ankii/__init__.py` match.
3. Select the smallest correct SemVer increment:
   - patch for fixes, maintenance, or internal changes;
   - minor for backward-compatible user-facing features;
   - major for breaking changes.
   - while the project remains below `1.0.0`, use patch for compatible fixes and minor for features or breaking pre-stable changes; move to `1.0.0` only when intentionally declaring a stable public contract.
4. If compatibility or the intended version is ambiguous, or the inference differs from a version named by the user, ask before changing files. Otherwise announce the inferred version.
5. Update both version declarations to the same new version. Do not reuse an existing version or tag.
6. Update user-facing documentation when commands, installation, configuration, or behavior changed. Do not create a changelog unless the repository adopts one.
7. Fetch current `origin/main` and tags before finalizing when network access is available. Check the proposed tag both locally and on `origin`; do not assume a locally absent tag is unused.

## Verify

Run from the repository root:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/ruff check .
git diff --check
```

Also build the wheel or source distribution with an available standard Python build tool, install it into a temporary isolated environment, and run `ankii --help` from that installed artifact. This verifies packaging metadata and the console entry point rather than only the source checkout.

If the project environment differs, use the equivalent working commands and report the substitution. Stop before committing or tagging if any required check fails. Distinguish failures caused by the release changes from pre-existing failures, but never tag an unverified release.

## Commit and tag

1. Review the final diff and confirm all files belonging to the update are included.
2. Stage only the release files. Do not absorb unrelated work merely to obtain a clean tree.
3. Create one release commit named `Release X.Y.Z` unless the user requests another conventional message.
4. Ensure the release commit contains the latest `origin/main`. Because pipx installations track `main`, create the tag only after the exact release commit is on local `main`. If the update still requires review or integration from another branch, prepare the commit but stop before tagging and report that remaining step.
5. Create an annotated tag on that exact commit:

```bash
git tag -a vX.Y.Z -m "Release X.Y.Z"
```

6. Verify that `vX.Y.Z` resolves to the release commit, the commit is reachable from `main`, and no release-scope changes remain unstaged.
7. Report the version, commit, tag, branch, package smoke-test result, test results, and any deliberately uncommitted files.

Treat a request to release or tag the completed update as authorization to create the local release commit and annotated tag. Treat an explicit request to publish, push, or ship to `origin` as authorization to push the release. Do not create a hosted release or publish a package registry artifact unless the user explicitly requests it. When authorized to push, push `main` first and then the exact tag after all verification succeeds; never use `--tags`.
