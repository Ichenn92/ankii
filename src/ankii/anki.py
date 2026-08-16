from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

ANKI_CONNECT_URL = "http://127.0.0.1:8765"
API_VERSION = 6


class AnkiConnectError(RuntimeError):
    pass


def invoke(action: str, *, request_timeout: float = 10, **params: Any) -> Any:
    payload = {"action": action, "version": API_VERSION}
    if params:
        payload["params"] = params
    request = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            body = json.load(response)
    except urllib.error.URLError as exc:
        raise AnkiConnectError(
            "Could not connect to AnkiConnect at http://127.0.0.1:8765. "
            "Open Anki and make sure the AnkiConnect add-on is installed."
        ) from exc
    except json.JSONDecodeError as exc:
        raise AnkiConnectError("AnkiConnect returned invalid JSON.") from exc

    if not isinstance(body, dict) or "result" not in body or "error" not in body:
        raise AnkiConnectError("AnkiConnect returned an unexpected response.")
    if body["error"] is not None:
        raise AnkiConnectError(f"AnkiConnect error: {body['error']}")
    return body["result"]
