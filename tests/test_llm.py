"""LLM adapters with fake clients: schema, retries, cache replay (no network)."""

from types import SimpleNamespace

import pytest

from invoice_extractor.llm import CachedExtractor, FallbackExtractor, GeminiExtractor, LLMResult, QuotaExhausted
from tests.test_pipeline import extraction


class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class FakeGemini:
    """Stands in for google.genai.Client: scripted replies or errors, records each call."""

    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        usage = SimpleNamespace(prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=50)
        return SimpleNamespace(text=outcome, usage_metadata=usage)


def test_gemini_sends_schema_and_parses_reply():
    client = FakeGemini([extraction().model_dump_json()])
    result = GeminiExtractor("gemini-x", client=client).extract("prompt")
    config = client.calls[0]["config"]
    assert config.response_mime_type == "application/json"
    assert "services" in config.response_json_schema["properties"]
    assert result.extraction == extraction()
    assert (result.input_tokens, result.output_tokens) == (1000, 250)  # thinking tokens are billed output


def test_gemini_retries_rate_limits_then_succeeds():
    client = FakeGemini([ApiError(429), ApiError(503), extraction().model_dump_json()])
    GeminiExtractor("gemini-x", client=client, retry_delay=0, attempts=3).extract("prompt")
    assert len(client.calls) == 3


def test_gemini_fails_fast_on_daily_quota():
    exhausted = ApiError(429)
    exhausted.args = ("429 RESOURCE_EXHAUSTED quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier",)
    client = FakeGemini([exhausted])
    gemini = GeminiExtractor("gemini-x", client=client, retry_delay=0)
    with pytest.raises(ApiError):
        gemini.extract("prompt")
    assert len(client.calls) == 1  # retrying a daily quota only burns requests
    with pytest.raises(QuotaExhausted):  # circuit breaker: later documents skip the network call
        gemini.extract("another prompt")
    assert len(client.calls) == 1


def test_gemini_does_not_retry_client_errors():
    client = FakeGemini([ApiError(400)])
    with pytest.raises(ApiError):
        GeminiExtractor("gemini-x", client=client, retry_delay=0).extract("prompt")
    assert len(client.calls) == 1


class Scripted:
    def __init__(self, model, outcome):
        self.model, self.outcome, self.calls = model, outcome, 0

    def extract(self, prompt, label=""):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return LLMResult(extraction(), self.model, 10, 5, 0.1)


def test_ladder_falls_through_quota_overload_and_cache_misses():
    rungs = [Scripted("a", ApiError(429)), Scripted("b", ApiError(503)), Scripted("c", LookupError("no cache")),
             Scripted("d", None), Scripted("e", None)]
    result = FallbackExtractor(rungs).extract("prompt")
    assert result.model == "d" and rungs[4].calls == 0


def test_ladder_does_not_hide_real_errors():
    rungs = [Scripted("a", ValueError("bad schema")), Scripted("b", None)]
    with pytest.raises(ValueError):
        FallbackExtractor(rungs).extract("prompt")
    assert rungs[1].calls == 0


def test_cache_replays_without_a_client(tmp_path):
    class Once:
        model, calls = "m", 0

        def extract(self, prompt, label=""):
            Once.calls += 1
            return LLMResult(extraction(), "m", 10, 5, 0.1)

    CachedExtractor(Once(), "m", tmp_path).extract("same prompt")
    replay = CachedExtractor(None, "m", tmp_path).extract("same prompt")
    assert replay.cached and replay.extraction == extraction() and Once.calls == 1
    with pytest.raises(LookupError):
        CachedExtractor(None, "m", tmp_path).extract("a different document")
