from __future__ import annotations

import re
import shutil
import subprocess
import tomllib
import urllib.request

from ankii import __version__

PROJECT_FILE_URL = (
    "https://raw.githubusercontent.com/Ichenn92/ankii/main/pyproject.toml"
)
def _version_key(value: str) -> tuple[int, ...] | None:
    if re.fullmatch(r"\d+(?:\.\d+)*", value) is None:
        return None
    return tuple(int(part) for part in value.split("."))


def _newer_version(latest: str, current: str = __version__) -> bool:
    latest_key = _version_key(latest)
    current_key = _version_key(current)
    return latest_key is not None and current_key is not None and latest_key > current_key


def _fetch_latest_version(*, timeout: float = 2.0) -> str:
    request = urllib.request.Request(
        PROJECT_FILE_URL,
        headers={"User-Agent": f"ankii/{__version__} update-check"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        project_file = tomllib.loads(response.read().decode("utf-8"))
    return str(project_file["project"]["version"])


def check_version() -> int:
    latest = _fetch_latest_version()
    print(f"Installed: {__version__}")
    print(f"Latest:    {latest}")
    if _newer_version(latest):
        print("An update is available. Run 'ankii upgrade' to install it.")
    else:
        print("ankii is up to date.")
    return 0


def upgrade() -> int:
    if shutil.which("pipx") is None:
        raise RuntimeError("pipx is not available. Install pipx before upgrading ankii.")
    result = subprocess.run(["pipx", "upgrade", "ankii"], check=False)
    if result.returncode != 0:
        raise RuntimeError("pipx could not upgrade ankii.")
    print("Upgrade complete. Restart ankii to use the new version.")
    return 0
