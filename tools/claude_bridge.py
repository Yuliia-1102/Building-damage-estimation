"""Claude subagents in place of Gemini during development (models/claude_bridge.py).

    DAMAGE_LLM=claude-sonnet-5-5 uv run python -m tools.run_testset testset/cases.csv --claude   # exports requests
    uv run python -m tools.claude_bridge list                 # what is waiting for an answer
    uv run python -m tools.claude_bridge prompt <folder>      # the task text for one subagent
    uv run python -m tools.claude_bridge import               # validate answers and put them in the cache

Repeat run_testset / subagents / import until nothing is pending (building parameters first, then decisions).
"""
import argparse
import json

from models import claude_bridge

TASK = """You stand in for a vision language model inside a building damage assessment system.

Read {folder}/request.json. It has:
- "system": your role and rules,
- "prompt": the task,
- "images": image files in the same folder; read every one of them before answering,
- "answer_schema": the JSON schema your answer must match exactly.

Answer exactly as that model would: follow "system" and "prompt", judge from the images and the numbers given.
Write ONLY the JSON object matching "answer_schema" (no prose, no code fence) to {folder}/answer.json.
Do not read or change any other file. Reply with one line: the JSON you wrote."""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    pr = sub.add_parser("prompt")
    pr.add_argument("folder")
    sub.add_parser("import")
    args = p.parse_args()

    if args.cmd == "list":
        for f in claude_bridge.pending():
            r = json.loads((f / "request.json").read_text(encoding="utf-8"))
            state = "answered" if (f / "answer.json").exists() else "waiting"
            print(f"{f}\t{r['schema_name']}\t{len(r['images'])} images\t{state}")
    elif args.cmd == "prompt":
        print(TASK.format(folder=args.folder))
    else:
        results = {f.name: claude_bridge.import_answer(f) for f in claude_bridge.pending()}
        for name, status in results.items():
            print(f"{status:10}\t{name}")
        print(f"imported {sum(s == 'ok' for s in results.values())} of {len(results)}")


if __name__ == "__main__":
    main()
