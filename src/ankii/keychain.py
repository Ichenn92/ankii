from __future__ import annotations

import getpass
import os
import platform
import subprocess

KEYCHAIN_SERVICE = "ankii-openai"
LEGACY_KEYCHAIN_SERVICES = ("yhw2anki-openai",)


def keychain_supported() -> bool:
    return platform.system() == "Darwin"


def _require_macos() -> None:
    if not keychain_supported():
        raise RuntimeError("Automatic secure key storage is currently supported only on macOS.")


def find_keychain_key() -> str | None:
    if not keychain_supported():
        return None
    for service in (KEYCHAIN_SERVICE, *LEGACY_KEYCHAIN_SERVICES):
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-a",
                getpass.getuser(),
                "-s",
                service,
                "-w",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def get_openai_api_key() -> tuple[str | None, str | None]:
    environment_key = os.environ.get("OPENAI_API_KEY")
    if environment_key:
        return environment_key, "environment"
    keychain_key = find_keychain_key()
    if keychain_key:
        return keychain_key, "macOS Keychain"
    return None, None


def store_keychain_key() -> None:
    _require_macos()
    print("Paste the OpenAI API key at the secure Keychain prompt, then press Return.")
    result = subprocess.run(
        [
            "/usr/bin/security",
            "add-generic-password",
            "-a",
            getpass.getuser(),
            "-s",
            KEYCHAIN_SERVICE,
            "-l",
            "ankii OpenAI API key",
            "-U",
            "-w",
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("The API key was not saved to macOS Keychain.")


def delete_keychain_key() -> bool:
    _require_macos()
    deleted = False
    for service in (KEYCHAIN_SERVICE, *LEGACY_KEYCHAIN_SERVICES):
        result = subprocess.run(
            [
                "/usr/bin/security",
                "delete-generic-password",
                "-a",
                getpass.getuser(),
                "-s",
                service,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        deleted = result.returncode == 0 or deleted
    return deleted
