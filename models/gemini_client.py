"""Shared Gemini plumbing: one structured JSON answer, validated, retried and cached.

Used by the decision layer and by the building parameters estimator, so both get the same
schema validation (task 6.1), retry on a malformed answer (6.1.3) and answer cache (6.2.3).
"""
import csv
import json
import logging
import os
import time
from datetime import datetime

from pydantic import BaseModel, ValidationError

from core import cache, config

log = logging.getLogger(__name__)


def make_client():
    from dotenv import load_dotenv
    from google import genai
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not set, see .env.example")
    return genai.Client()


def llm_model(kind: str) -> str:
    """The model for 'decision' or 'building'. DAMAGE_LLM (e.g. claude-sonnet-5-5) overrides both while the
    system is developed with Claude subagents instead of Gemini (models/claude_bridge.py)."""
    return os.environ.get("DAMAGE_LLM") or config.get("decision", "model" if kind == "decision" else "building_model")


class GeminiJSON:
    def __init__(self, client=None, model: str | None = None, retries: int = 2, use_cache: bool = True):
        self.model = model or llm_model("decision")
        self.bridge = self.model.startswith("claude-")      # no API: requests go to subagents through files
        self.client = client or (None if self.bridge else make_client())
        self.retries = retries
        self.use_cache = use_cache
        self.last_from_cache: bool | None = None    # whether the last answer came from the cache (no request)

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

    def ask(self, contents: list, schema: type[BaseModel], system: str, namespace: str, key_parts: list[str]):
        """contents: text and image parts for the request. key_parts: what identifies the request in the cache
        (the prompt text and the hashes of any images)."""
        key = cache.text_key("\n".join([self.model, system, *key_parts]))
        if self.use_cache and (hit := cache.get_json(namespace, key)) is not None:
            self.last_from_cache = True
            return schema.model_validate(hit)
        self.last_from_cache = False
        if self.bridge and self.client is None:
            from models.claude_bridge import AnswerPending, export
            folder = export(self.model, namespace, key, contents, schema, system)
            raise AnswerPending(f"waiting for a {self.model} answer: {folder.name}")

        last_error = None
        for attempt in range(1, self.retries + 2):
            raw = self._call(contents, schema, system)
            try:
                answer = schema.model_validate_json(raw)
                break
            except ValidationError as e:
                last_error = e
                log.warning("%s attempt %d: response does not match the schema: %s", namespace, attempt, raw)
        else:
            raise ValueError(f"no valid {namespace} answer after {self.retries + 1} attempts") from last_error

        if self.use_cache:
            cache.put_json(namespace, key, json.loads(answer.model_dump_json()))
        return answer
