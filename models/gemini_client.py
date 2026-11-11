"""Shared Gemini plumbing: one structured JSON answer, validated and retried.

Used by the decision layer and by the building parameters estimator, so both get the same
schema validation and retry on a malformed answer. Every call is a new request: answers are not cached.
"""
import csv
import json
import logging
import os
import time
from datetime import datetime

from pydantic import BaseModel, ValidationError

from core import config

log = logging.getLogger(__name__)


def make_client():
    from dotenv import load_dotenv
    from google import genai
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not set, see .env.example")
    return genai.Client()


def llm_model(kind: str) -> str:
    """The Gemini model for 'decision' or 'building' (config.toml, [decision])."""
    return config.get("decision", "model" if kind == "decision" else "building_model")


class GeminiJSON:
    def __init__(self, client=None, model: str | None = None, retries: int = 2):
        self.model = model or llm_model("decision")
        self.client = client or make_client()
        self.retries = retries

    def _call(self, contents: list, schema: type[BaseModel], system: str) -> str:
        """One request; on 429 (rate limit) or 503 (overloaded) waits 2, 4, 8 ... seconds and tries again."""
        from google.genai import errors
        attempts = config.get("decision", "retry_on_overload")
        for attempt in range(attempts):
            try:
                return self._request(contents, schema, system)
            except errors.APIError as e:
                if e.code not in (429, 500, 503) or attempt == attempts - 1:
                    raise
                wait = 2 ** (attempt + 1)
                log.warning("Gemini %s, retrying in %ds", e.code, wait)
                time.sleep(wait)

    def _request(self, contents: list, schema: type[BaseModel], system: str) -> str:
        from google.genai import types
        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.0,
                seed=config.get("decision", "seed"),
            ),
        )
        self._log_usage(schema.__name__, getattr(response, "usage_metadata", None))
        return response.text

    def _log_usage(self, what: str, usage) -> None:
        """One row per paid request in output/gemini_usage.csv: what was asked and how many tokens it took."""
        if usage is None:
            return
        row = {"time": datetime.now().isoformat(timespec="seconds"), "model": self.model, "request": what,
               "input": usage.prompt_token_count or 0, "output": usage.candidates_token_count or 0,
               "thinking": usage.thoughts_token_count or 0}
        log.info("Gemini usage: %s", row)
        path = config.path("output") / "gemini_usage.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)

    def ask(self, contents: list, schema: type[BaseModel], system: str, namespace: str):
        """contents: text and image parts for the request. namespace names the request in the log."""
        last_error = None
        for attempt in range(1, self.retries + 2):
            raw = self._call(contents, schema, system)
            try:
                return schema.model_validate_json(raw)
            except ValidationError as e:
                last_error = e
                log.warning("%s attempt %d: response does not match the schema: %s", namespace, attempt, raw)
        raise ValueError(f"no valid {namespace} answer after {self.retries + 1} attempts") from last_error
