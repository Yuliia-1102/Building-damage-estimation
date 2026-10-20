"""Claude (via Claude Code subagents) as a stand-in for Gemini while the system is being developed.

The app cannot call a subagent, so the exchange goes through files and the answer cache:
  1. With a `claude-*` model, a request that is not in the cache is written to output/claude_requests/<id>/:
     request.json (system instruction, prompt, JSON schema of the answer) and image1.jpg, image2.jpg ...
     Nothing is sent anywhere; the step that needed it reports the answer as pending.
  2. A subagent reads one request folder and writes answer.json next to it (tools/claude_bridge.py prompt).
  3. `uv run python -m tools.claude_bridge import` validates every answer against the same schema as a Gemini
     answer and puts it into the cache under the model name, so the next run takes it from there.
Answers of Claude and Gemini never mix: the model name is part of the cache key.
"""
import json
import shutil
from pathlib import Path

from pydantic import BaseModel

from core import config


class AnswerPending(RuntimeError):
    """The request was exported for a subagent; its answer is not in the cache yet."""
    pending = True      # core.pipeline stops the case here: later steps need this answer


def requests_dir() -> Path:
    return config.path("output") / "claude_requests"


def export(model: str, namespace: str, key: str, contents: list, schema: type[BaseModel], system: str) -> Path:
    folder = requests_dir() / f"{namespace}_{key[:16]}"
    folder.mkdir(parents=True, exist_ok=True)
    texts, n = [], 0
    for part in contents:
        if isinstance(part, str):
            texts.append(part)
            continue
        data = getattr(getattr(part, "inline_data", None), "data", None)
        if data:
            n += 1
            (folder / f"image{n}.jpg").write_bytes(data)
    request = {"model": model, "namespace": namespace, "key": key, "schema_name": schema.__name__,
               "system": system, "prompt": "\n\n".join(texts), "images": [f"image{i}.jpg" for i in range(1, n + 1)],
               "answer_schema": schema.model_json_schema()}
    (folder / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


def pending() -> list[Path]:
    root = requests_dir()
    return sorted(p for p in root.iterdir() if (p / "request.json").exists()) if root.exists() else []


SCHEMAS = {}


def _schemas() -> dict[str, type[BaseModel]]:
    if not SCHEMAS:
        from models.gemini_building import BuildingResponse
        from models.gemini_decision import DecisionResponse
        SCHEMAS.update(BuildingResponse=BuildingResponse, DecisionResponse=DecisionResponse)
    return SCHEMAS


def import_answer(folder: Path) -> str:
    """Validate answer.json and cache it. Returns 'ok', 'missing' or the validation error."""
    from core import cache
    answer_file = folder / "answer.json"
    if not answer_file.exists():
        return "missing"
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    schema = _schemas()[request["schema_name"]]
    text = answer_file.read_text(encoding="utf-8").strip()
    if text.startswith("```"):                       # tolerate a fenced block
        text = text.strip("`").removeprefix("json").strip()
    try:
        answer = schema.model_validate_json(text)
    except Exception as e:                           # the answer stays for a rerun of that subagent
        return f"invalid: {str(e).splitlines()[0]}"
    cache.put_json(request["namespace"], request["key"], json.loads(answer.model_dump_json()))
    done = requests_dir() / "_done" / folder.name
    if done.exists():
        shutil.rmtree(done)
    shutil.move(str(folder), done)
    return "ok"
