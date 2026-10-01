"""LLM access: one structured-output call per document, behind a content-addressed cache.

Two providers implement the same `extract` method (Google Gemini and OpenAI, both with a JSON
schema on the response); nothing else in the pipeline knows which model answered.
"""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .prompts import PROMPT_VERSION, SYSTEM_PROMPT
from .schema import InvoiceExtraction


@dataclass
class LLMResult:
    extraction: InvoiceExtraction
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cached: bool = False


class Extractor(Protocol):
    model: str

    def extract(self, user_prompt: str, label: str = "") -> LLMResult: ...


class QuotaExhausted(Exception):
    code = 429


class GeminiExtractor:
    """Google Gemini (AI Studio API key) with the response constrained to the JSON schema."""

    RETRYABLE = {429, 500, 503}

    def __init__(self, model: str, client=None, retry_delay: float = 15.0, attempts: int = 2):
        if client is None:
            from google import genai

            client = genai.Client()  # reads GEMINI_API_KEY
        self.model = model
        self.client = client
        self.retry_delay = retry_delay
        self.attempts = attempts
        self.exhausted = False  # circuit breaker: set once the daily quota is reported used up

    def extract(self, user_prompt: str, label: str = "") -> LLMResult:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=InvoiceExtraction.model_json_schema(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        started = time.perf_counter()
        response = self._generate(user_prompt, config, label)
        if not response.text:
            raise RuntimeError(f"{label}: empty response from {self.model}")
        usage = response.usage_metadata
        return LLMResult(
            extraction=InvoiceExtraction.model_validate_json(response.text),
            model=self.model,
            input_tokens=usage.prompt_token_count or 0,
            output_tokens=(usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
            latency_s=round(time.perf_counter() - started, 2),
        )

    def _generate(self, user_prompt: str, config, label: str):
        # Per-minute limits and overload clear up, so back off and retry. A daily quota does not:
        # retrying it only burns requests, so fail fast and let the row go to review.
        if self.exhausted:
            raise QuotaExhausted(f"{label}: {self.model} daily quota already used up in this run")
        for attempt in range(self.attempts):
            try:
                return self.client.models.generate_content(model=self.model, contents=user_prompt, config=config)
            except Exception as exc:
                daily_quota = "PerDay" in str(exc)
                self.exhausted = self.exhausted or daily_quota
                if getattr(exc, "code", None) not in self.RETRYABLE or daily_quota or attempt == self.attempts - 1:
                    raise
                time.sleep(self.retry_delay * 2 ** attempt)
        raise RuntimeError(f"{label}: unreachable")


class OpenAIExtractor:
    """OpenAI Responses API with a strict JSON schema: the reply always parses into the schema."""

    def __init__(self, model: str, reasoning_effort: str = "low", client=None):
        from openai import OpenAI

        self.model = model
        self.reasoning_effort = reasoning_effort
        self.client = client or OpenAI(max_retries=4, timeout=300)

    def extract(self, user_prompt: str, label: str = "") -> LLMResult:
        is_reasoning_model = self.model.startswith(("gpt-5", "o1", "o3", "o4"))
        options = {"reasoning": {"effort": self.reasoning_effort}} if is_reasoning_model else {"temperature": 0}
        started = time.perf_counter()
        response = self.client.responses.parse(
            model=self.model,
            instructions=SYSTEM_PROMPT,
            input=user_prompt,
            text_format=InvoiceExtraction,
            **options,
        )
        if response.output_parsed is None:
            raise RuntimeError(f"{label}: no parsable output (status={response.status})")
        return LLMResult(
            extraction=response.output_parsed,
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_s=round(time.perf_counter() - started, 2),
        )


class FallbackExtractor:
    """An ordered model ladder: when one model is out of quota or overloaded, try the next.

    Free tiers cap requests per model per day, and overload (503) is common on new models, so a
    single model is a single point of failure. Each answer records which model produced it.
    """

    def __init__(self, extractors: list):
        self.extractors = extractors
        self.model = extractors[0].model

    def extract(self, user_prompt: str, label: str = "") -> LLMResult:
        failures = []
        for extractor in self.extractors:
            try:
                return extractor.extract(user_prompt, label)
            except Exception as exc:
                if not _is_capacity_error(exc):
                    raise
                failures.append(f"{extractor.model}: {str(exc)[:60]}")
        raise RuntimeError(f"{label}: every model in the ladder failed: " + " | ".join(failures))


def _is_capacity_error(exc: Exception) -> bool:
    # LookupError = no cached answer in offline mode, so the next model's cache is tried.
    return isinstance(exc, LookupError) or getattr(exc, "code", None) in (429, 500, 503)


class CachedExtractor:
    """Replays a stored answer when model, prompt, schema and document text are all unchanged."""

    def __init__(self, inner: Extractor | None, model: str, cache_dir: Path):
        self.inner = inner  # None = offline: only cached answers are available
        self.model = model
        self.cache_dir = cache_dir

    def extract(self, user_prompt: str, label: str = "") -> LLMResult:
        path = self.cache_dir / f"{self._key(user_prompt)}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return LLMResult(
                extraction=InvoiceExtraction.model_validate(data["extraction"]),
                model=data["model"],
                input_tokens=data["input_tokens"],
                output_tokens=data["output_tokens"],
                latency_s=data["latency_s"],
                cached=True,
            )
        if self.inner is None:
            raise LookupError(f"{label}: no cached answer for model {self.model}; add an API key to run live")
        result = self.inner.extract(user_prompt, label)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "label": label,
            "model": result.model,
            "prompt_version": PROMPT_VERSION,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_s": result.latency_s,
            "extraction": result.extraction.model_dump(),
        }
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _key(self, user_prompt: str) -> str:
        schema = json.dumps(InvoiceExtraction.model_json_schema(), sort_keys=True)
        material = "\x1f".join([self.model, SYSTEM_PROMPT, schema, user_prompt])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
