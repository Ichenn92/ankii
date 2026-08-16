import json

from ankii.commons import search_commons


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_search_commons_extracts_image_and_license(monkeypatch) -> None:
    payload = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Cat.jpg",
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/full.jpg",
                            "thumburl": "https://upload.wikimedia.org/thumb.jpg",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Cat.jpg",
                            "extmetadata": {
                                "Artist": {"value": "<b>Example Author</b>"},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "LicenseUrl": {"value": "https://creativecommons.org/license"},
                            },
                        }
                    ],
                }
            }
        }
    }
    monkeypatch.setattr(
        "ankii.commons.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    result = search_commons("cat")

    assert len(result) == 1
    assert result[0].title == "Cat.jpg"
    assert result[0].attribution == "Example Author — CC BY-SA 4.0"
    assert result[0].image_url.endswith("thumb.jpg")
