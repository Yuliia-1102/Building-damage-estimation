"""Run every test case with one command and save everything needed to analyse the run (tasks 9.3, 9.4).

    uv run python -m tools.run_testset testset/cases.csv                          # cache only, free
    uv run python -m tools.run_testset testset/cases.csv --gemini --name step-a   # paid requests
    uv run python -m tools.run_testset testset/cases.csv --gemini --repeat 3 --no-decision-cache --name consistency

Each run gets its own folder output/runs/<date-time>_<name>/:
  summary.md        results against the expected categories, requests and cost of the run
  results.csv       one row per case and run (also copied to output/testset.csv)
  manifest.json     when, git commit, models, arguments, config.toml as used, token totals
  usage.csv         every paid Gemini request of this run with its tokens
  run.log           the full log
  cases/<case_id>/  report.json (the whole report), decision_prompt.txt, views/ (masks and overlays)

A case that crashes is recorded with its error and the run goes on. Masks are cached, so repeats only
re-run the language model; --no-decision-cache makes every repeat ask the model again, which is what
the consistency check needs. Without --gemini nothing is sent: cached answers, stubs otherwise.
"""
import argparse
import csv
import dataclasses
import glob
import json
import logging
import os
import shutil
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path

from core import config
from core.cache import CachedSegmenter
from core.case import case_from_paths, case_from_video
from core.output import save_views
from core.pipeline import evaluate, segment_case
from core.video import VIDEO_EXTS
from models.gemini_client import llm_model
from models.price_source import default_price_source

log = logging.getLogger("testset")

COLUMNS = ["case_id", "run", "kind", "mode", "views", "expected_damage", "expected_condition",
           "damage_category", "condition_category", "damage_ok", "condition_ok", "confidence", "escalation",
           "damaged_facade", "broken_window", "damaged_roof", "worst_facade", "worst_section",
           "damage_lower_third", "floors", "height_m", "width_m", "structure", "roof_type", "consequence_class",
           "works", "cost_low", "cost_high", "building_source", "decision_source", "seconds", "error"]

# USD per 1M tokens (input, output incl. thinking), Gemini API standard tier, checked 2026-10-17
PRICES_USD = {"gemini-3.8-flash": (0.75, 3.75), "gemini-3.1-flash-lite": (0.25, 1.50),
              "gemini-3.5-flash-lite": (0.30, 2.50)}


def build_case(row: dict, root: Path, quick_segmenter=None):
    src = row["input"]
    paths = sorted(Path(p) for p in glob.glob(str(root / src)))
    if not paths:
        raise FileNotFoundError(src)
    if len(paths) == 1 and paths[0].suffix.lower() in VIDEO_EXTS:
        case, _ = case_from_video(paths[0], config.path("cases") / "_video", quick_segmenter)
        case.case_id = row["case_id"]
        return case
    return case_from_paths(row["case_id"], paths)


def fmt(x, nd=3):
    return "" if x is None else (round(x, nd) if isinstance(x, float) else x)


def matches(value, expected: str) -> str:
    """'II' against 'II-III' -> yes. Empty when there is nothing to compare."""
    if value in (None, "") or not expected:
        return ""
    return "yes" if str(value) in expected.split("-") else "no"


def answer_source(layer) -> str:
    """Where the last answer came from: a new Gemini request, the cache, or a stub."""
    if hasattr(layer, "last_source"):                       # offline layers
        return layer.last_source or ""
    if hasattr(layer, "llm"):
        return "cache" if layer.llm.last_from_cache else "gemini"
    return "stub"


def report_json(report) -> str:
    d = dataclasses.asdict(dataclasses.replace(report, masks={}, excluded={}))
    d.pop("masks")
    d.pop("excluded")
    return json.dumps(d, indent=2, ensure_ascii=False, default=list)


def git_state() -> dict:
    def run(*cmd):
        try:
            return subprocess.run(cmd, cwd=config.ROOT, capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""
    return {"commit": run("git", "rev-parse", "--short", "HEAD"),
            "uncommitted_changes": bool(run("git", "status", "--porcelain", "--untracked-files=no"))}


def run_usage(start: datetime) -> list[dict]:
    path = config.path("output") / "gemini_usage.csv"
    if not path.exists():
        return []
    return [r for r in csv.DictReader(open(path, encoding="utf-8")) if r["time"] >= start.isoformat(timespec="seconds")]


def usage_totals(rows: list[dict]) -> dict:
    by_model = {}
    for r in rows:
        m = by_model.setdefault(r["model"], {"requests": 0, "input": 0, "output": 0, "thinking": 0})
        m["requests"] += 1
        for k in ("input", "output", "thinking"):
            m[k] += int(r[k])
    for model, m in by_model.items():
        price_in, price_out = PRICES_USD.get(model, (0, 0))
        m["cost_usd"] = round((m["input"] * price_in + (m["output"] + m["thinking"]) * price_out) / 1e6, 5)
    return by_model


def write_summary(run_dir: Path, rows: list[dict], manifest: dict) -> None:
    lines = [f"# Test set run {run_dir.name}", "",
             f"Commit {manifest['git']['commit']}"
             f"{' (with uncommitted changes)' if manifest['git']['uncommitted_changes'] else ''}, "
             f"models: building {manifest['models']['building']}, decision {manifest['models']['decision']}, "
             f"gemini requests allowed: {manifest['args']['gemini']}.", "",
             "| case | run | expected | got | ok | confidence | worst view | worst section | floors | structure "
             "| roof | cost, UAH | answers | error |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ok = f"{r['damage_ok'] or '-'}/{r['condition_ok'] or '-'}"
        cost = f"{r['cost_low']:,}–{r['cost_high']:,}".replace(",", " ") if r["cost_low"] != "" else ""
        lines.append(f"| {r['case_id']} | {r['run']} | {r['expected_damage']} / {r['expected_condition']} "
                     f"| {r['damage_category']} / {r['condition_category']} | {ok} | {r['confidence']} "
                     f"| {r['worst_facade']} | {r['worst_section']} | {r['floors']} | {r['structure']} "
                     f"| {r['roof_type']} | {cost} | {r['building_source']}, {r['decision_source']} "
                     f"| {str(r['error'])[:80]} |")
    judged = [r for r in rows if r["damage_ok"]]
    lines += ["", f"Damage category matches the expectation in {sum(r['damage_ok'] == 'yes' for r in judged)} "
                  f"of {len(judged)}; condition category in "
                  f"{sum(r['condition_ok'] == 'yes' for r in judged)} of {len(judged)}.",
              "Expectations are a draft from a visual review (testset/cases.csv).", "", "## Gemini requests", ""]
    totals = manifest["usage"]
    if totals:
        lines += ["| model | requests | input | output | thinking | cost, USD |", "|---|---|---|---|---|---|"]
        for model, m in totals.items():
            lines.append(f"| {model} | {m['requests']} | {m['input']} | {m['output']} | {m['thinking']} "
                         f"| {m['cost_usd']} |")
    else:
        lines.append("No paid requests in this run.")
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cases", type=Path)
    p.add_argument("--name", default="testset", help="label in the run folder name")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--no-decision-cache", action="store_true")
    p.add_argument("--stub", action="store_true", help="stub segmentation and decision (pipeline check only)")
    p.add_argument("--gemini", action="store_true",
                   help="send paid Gemini requests; without it only cached answers are used, stubs otherwise")
    p.add_argument("--only", nargs="*", help="case ids to run")
    p.add_argument("--decision-model", help="decision model for this run instead of config.toml (comparisons)")
    p.add_argument("--claude", action="store_true",
                   help="Claude subagents instead of Gemini (DAMAGE_LLM, default claude-sonnet-5-5): requests not in "
                        "the cache are exported for tools/claude_bridge.py, nothing is sent or paid")
    p.add_argument("--no-views", action="store_true", help="do not save masks and overlays")
    args = p.parse_args()

    start = datetime.now()
    run_dir = config.path("output") / "runs" / f"{start:%Y-%m-%d_%H%M%S}_{args.name}"
    (run_dir / "cases").mkdir(parents=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(run_dir / "run.log"), logging.StreamHandler()])
    shutil.copy(config.CONFIG_PATH, run_dir / "config.toml")

    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    if args.claude:
        os.environ.setdefault("DAMAGE_LLM", "claude-sonnet-5-5")
    use_llm = (args.claude or (args.gemini and bool(os.environ.get("GEMINI_API_KEY")))) and not args.stub
    if args.stub:
        from models.stub import StubSegmenter
        segmenter = StubSegmenter()
    else:
        from models.dinov2_unet import DinoV2Segmenter
        segmenter = CachedSegmenter(DinoV2Segmenter(), config.path("weights").stem)
    if use_llm:
        from models.gemini_building import GeminiBuildingEstimator
        from models.gemini_decision import GeminiDecisionLayer
        building = GeminiBuildingEstimator()
    elif args.stub:
        from models.stub import StubBuildingParams, StubDecisionLayer
        building, decision = StubBuildingParams(), StubDecisionLayer()
    else:
        from models.offline import CachedOrStubBuilding, CachedOrStubDecision
        building, decision = CachedOrStubBuilding(), CachedOrStubDecision()
        log.warning("no --gemini: cached Gemini answers only, stubs where nothing is cached")
    from models.gemini_decision import build_prompt

    from core.cache import quick_segmenter
    quick = None if args.stub else quick_segmenter(segmenter)

    root = args.cases.resolve().parent.parent       # paths in cases.csv are relative to the repository
    rows = list(csv.DictReader(open(args.cases, encoding="utf-8")))
    if args.only:
        rows = [r for r in rows if r["case_id"] in args.only]
    segs, results = {}, []

    with open(run_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for run in range(1, args.repeat + 1):
            if use_llm:
                decision = GeminiDecisionLayer(model=args.decision_model, use_cache=not args.no_decision_cache)
            for row in rows:
                t = time.time()
                out = dict.fromkeys(COLUMNS, "")
                out.update(case_id=row["case_id"], run=run, kind=row["kind"],
                           expected_damage=row["expected_damage"], expected_condition=row["expected_condition"])
                case_dir = run_dir / "cases" / row["case_id"]
                case_dir.mkdir(exist_ok=True)
                try:
                    if row["case_id"] not in segs:
                        segs[row["case_id"]] = segment_case(build_case(row, root, quick), segmenter)
                        if not args.no_views:
                            save_views(segs[row["case_id"]], case_dir / "views")
                    seg = segs[row["case_id"]]
                    r = evaluate(seg, building_estimator=building, decision_layer=decision,
                                 price_source=default_price_source())
                    c, b, d, k = r.ratios, r.building, r.decision, r.cost
                    out.update(mode=r.mode, views=r.views_assessed, damaged_facade=fmt(c.damaged_facade),
                               broken_window=fmt(c.broken_window), damaged_roof=fmt(c.damaged_roof),
                               worst_facade=fmt(c.worst_facade_damage), worst_section=fmt(c.worst_section_damage),
                               damage_lower_third=fmt(c.damage_by_third[0] if c.damage_by_third else None),
                               building_source=answer_source(building) if b else "",
                               decision_source=answer_source(decision) if d else "")
                    if b:
                        out.update(floors=b.floors, height_m=fmt(b.height_m, 1), width_m=fmt(b.width_m, 1),
                                   structure=b.structure_type, roof_type=b.roof_type,
                                   consequence_class=b.consequence_class)
                    if d:
                        out.update(damage_category=d.damage_category, condition_category=d.condition_category,
                                   damage_ok=matches(d.damage_category, row["expected_damage"]),
                                   condition_ok=matches(d.condition_category, row["expected_condition"]),
                                   confidence=d.confidence, escalation=d.escalation,
                                   works=" ".join(wi.work_type for wi in d.works))
                    if k:
                        out.update(cost_low=round(k.low), cost_high=round(k.high))
                    out["error"] = "; ".join(r.errors)
                    suffix = "" if args.repeat == 1 else f"_run{run}"
                    (case_dir / f"report{suffix}.json").write_text(report_json(r), encoding="utf-8")
                    (case_dir / "decision_prompt.txt").write_text(build_prompt(c, r.areas, b), encoding="utf-8")
                    layer = getattr(decision, "gemini", decision)          # offline wraps the Gemini layer
                    for n, data in enumerate(getattr(layer, "last_images", []), start=1):
                        (case_dir / f"decision_image{n}.jpg").write_bytes(data)
                except Exception as e:      # a crashed case is recorded, the run goes on (task 9.3.3)
                    log.error("case %s failed:\n%s", row["case_id"], traceback.format_exc())
                    out["error"] = f"{type(e).__name__}: {e}"
                out["seconds"] = round(time.time() - t, 1)
                w.writerow(out)
                f.flush()
                results.append(out)
                log.info("run %d case %s: %s / %s (%s, %s) in %.1fs", run, row["case_id"], out["damage_category"],
                         out["condition_category"], out["building_source"], out["decision_source"], out["seconds"])

    usage = run_usage(start)
    if usage:
        with open(run_dir / "usage.csv", "w", newline="", encoding="utf-8") as f:
            uw = csv.DictWriter(f, fieldnames=list(usage[0]))
            uw.writeheader()
            uw.writerows(usage)
    manifest = {
        "started": start.isoformat(timespec="seconds"), "finished": datetime.now().isoformat(timespec="seconds"),
        "git": git_state(), "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "models": {"building": llm_model("building"), "decision": args.decision_model or llm_model("decision")},
        "price_source": config.get("prices", "source"), "usage": usage_totals(usage),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    write_summary(run_dir, results, manifest)
    shutil.copy(run_dir / "results.csv", config.path("output") / "testset.csv")
    print(f"run saved to {run_dir}")


if __name__ == "__main__":
    main()
