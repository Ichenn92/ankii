import sys
from types import SimpleNamespace

from ankii.tagging import suggest_example_sentence


def test_suggest_example_sentence_uses_structured_response(monkeypatch) -> None:
    captured = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=SimpleNamespace(
                    vietnamese="  Tôi uống cà phê mỗi sáng. ",
                    english=" I drink coffee every morning. ",
                )
            )

    class FakeOpenAI:
        def __init__(self, api_key):
            assert api_key == "test-key"
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    result = suggest_example_sentence("cà phê", "coffee", "test-model")

    assert result == ("Tôi uống cà phê mỗi sáng.", "I drink coffee every morning.")
    assert captured["model"] == "test-model"
    assert captured["store"] is False
