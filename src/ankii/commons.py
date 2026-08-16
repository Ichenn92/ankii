from __future__ import annotations

import html
import json
import re
import tempfile
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_URL = "https://commons.wikimedia.org/w/api.php"


@dataclass(frozen=True)
class CommonsImage:
    title: str
    image_url: str
    thumbnail_url: str
    source_url: str
    attribution: str
    license_url: str

    def card_fields(self) -> dict[str, str]:
        return {
            "image_url": self.image_url,
            "image_source_url": self.source_url,
            "image_attribution": self.attribution,
            "image_license_url": self.license_url,
        }


def _metadata_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key, {})
    raw = str(value.get("value", "")).strip() if isinstance(value, dict) else ""
    return html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()


def search_commons(query: str, *, limit: int = 8) -> list[CommonsImage]:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": 360,
            "origin": "*",
        }
    )
    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"User-Agent": "ankii/0.1 (personal vocabulary tool)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)

    pages = payload.get("query", {}).get("pages", {})
    results: list[CommonsImage] = []
    for page in pages.values() if isinstance(pages, dict) else ():
        info_list = page.get("imageinfo", [])
        if not info_list:
            continue
        info = info_list[0]
        metadata = info.get("extmetadata", {})
        creator = _metadata_value(metadata, "Artist") or _metadata_value(metadata, "Credit")
        license_name = _metadata_value(metadata, "LicenseShortName") or "License unspecified"
        attribution = " — ".join(value for value in (creator, license_name) if value)
        results.append(
            CommonsImage(
                title=str(page.get("title", "Untitled")).removeprefix("File:"),
                image_url=str(info.get("thumburl") or info.get("url") or ""),
                thumbnail_url=str(info.get("thumburl") or info.get("url") or ""),
                source_url=str(info.get("descriptionurl") or ""),
                attribution=attribution,
                license_url=_metadata_value(metadata, "LicenseUrl"),
            )
        )
    return [result for result in results if result.image_url]


def open_gallery(images: list[CommonsImage], query: str) -> Path:
    cards = []
    for index, image in enumerate(images, start=1):
        cards.append(
            f'<article><strong>{index}. {html.escape(image.title)}</strong>'
            f'<img src="{html.escape(image.thumbnail_url, quote=True)}" alt="">'
            f'<p>{html.escape(image.attribution)}</p>'
            f'<a href="{html.escape(image.source_url, quote=True)}">Commons source</a></article>'
        )
    document = f"""<!doctype html><meta charset="utf-8">
<title>Commons images for {html.escape(query)}</title>
<style>
body{{font:16px system-ui;margin:2rem}}
main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}}
article{{border:1px solid #ccc;padding:1rem}}
img{{display:block;width:100%;height:220px;object-fit:contain;margin:.7rem 0}}
p{{font-size:.85rem}}
</style>
<h1>Commons images for “{html.escape(query)}”</h1><main>{''.join(cards)}</main>"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", prefix="ankii-commons-", encoding="utf-8", delete=False
    ) as stream:
        stream.write(document)
        path = Path(stream.name)
    if not webbrowser.open(path.as_uri()):
        raise RuntimeError("The browser did not open the image gallery.")
    return path
