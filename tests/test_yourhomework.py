import pytest

from ankii.yourhomework import extract_public_id, make_absolute_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("313789981", "313789981"),
        (" https://yourhomework.net/vocab/313789981/ ", "313789981"),
    ],
)
def test_extract_public_id(value: str, expected: str) -> None:
    assert extract_public_id(value) == expected


def test_extract_public_id_rejects_non_numeric_value() -> None:
    with pytest.raises(ValueError):
        extract_public_id("not-a-lesson")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("/media/image.jpg", "https://yourhomework.net/media/image.jpg"),
        ("media/image.jpg", "https://yourhomework.net/media/image.jpg"),
        ("https://cdn.example/image.jpg", "https://cdn.example/image.jpg"),
    ],
)
def test_make_absolute_url(value: str, expected: str) -> None:
    assert make_absolute_url(value) == expected
