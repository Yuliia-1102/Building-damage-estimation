"""Run every test case with one command and write one table (tasks 9.3, 9.4).

    uv run python -m tools.run_testset testset/cases.csv --out output/testset.csv
    uv run python -m tools.run_testset testset/cases.csv --repeat 3 --no-decision-cache   # consistency check

A case that crashes is recorded with its error and the run goes on. Masks are cached, so repeats only
re-run the language model; --no-decision-cache makes every repeat ask the model again, which is what
the consistency check needs.
"""
import argparse
import csv
import glob
import logging
import os
import time
import traceback
from pathlib import Path

from core import config
from core.cache import CachedSegmenter
from core.case import case_from_paths, case_from_video
from core.pipeline import evaluate, segment_case
from core.video import VIDEO_EXTS
from models.csv_prices import CsvPriceSource

log = logging.getLogger("testset")

COLUMNS = ["case_id", "run", "kind", "mode", "views", "damaged_facade", "broken_window", "damaged_roof",
           "worst_facade", "damage_lower_third", "floors", "height_m", "width_m", "structure",
           "consequence_class", "damage_category", "condition_category", "confidence", "escalation",
           "cost_low", "cost_high", "seconds", "error"]


def build_case(row: dict, root: Path, embedder_factory):
    src = row["input"]
    paths = sorted(Path(p) for p in glob.glob(str(root / src)))
    if not paths:
        raise FileNotFoundError(src)
    if len(paths) == 1 and paths[0].suffix.lower() in VIDEO_EXTS:
        case, _ = case_from_video(paths[0], config.path("cases") / "_video", embedder_factory())
        case.case_id = row["case_id"]
        return case
    case = case_from_paths(row["case_id"], paths)
    return case


def fmt(x, nd=3):
    return "" if x is None else (round(x, nd) if isinstance(x, float) else x)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cases", type=Path)
    p.add_argument("--out", type=Path, default=Path("output/testset.csv"))
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--no-decision-cache", action="store_true")
    p.add_argument("--stub", action="store_true", help="stub segmentation and decision (pipeline check only)")
    p.add_argument("--only", nargs="*", help="case ids to run")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler("output/testset.log"), logging.StreamHandler()])

    from dotenv import load_dotenv
    load_dotenv(config.ROOT / ".env")
    use_llm = bool(os.environ.get("GEMINI_API_KEY")) and not args.stub
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
    else:
        from models.stub import StubBuildingParams, StubDecisionLayer
        building, decision = StubBuildingParams(), StubDecisionLayer()
        log.warning("no GEMINI_API_KEY or --stub: building parameters and decision are stubs")

    embedder = None

    def get_embedder():
        nonlocal embedder
        if embedder is None:
            from models.dino_embedder import DinoEmbedder
            embedder = DinoEmbedder()
        return embedder

    root = args.cases.resolve().parent.parent       # paths in cases.csv are relative to the repository
    rows = list(csv.DictReader(open(args.cases, encoding="utf-8")))
    if args.only:
        rows = [r for r in rows if r["case_id"] in args.only]
    prices = CsvPriceSource()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    segs = {}

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for run in range(1, args.repeat + 1):
            if use_llm:
                decision = GeminiDecisionLayer(use_cache=not args.no_decision_cache)
            for row in rows:
                t = time.time()
                out = {"case_id": row["case_id"], "run": run, "kind": row["kind"]}
                try:
                    if row["case_id"] not in segs:
                        segs[row["case_id"]] = segment_case(build_case(row, root, get_embedder), segmenter)
                    seg = segs[row["case_id"]]
                    r = evaluate(seg, building_estimator=building, decision_layer=decision, price_source=prices)
                    c, b, d, k = r.ratios, r.building, r.decision, r.cost
                    out.update(mode=r.mode, views=r.views_assessed, damaged_facade=fmt(c.damaged_facade),
                               broken_window=fmt(c.broken_window), damaged_roof=fmt(c.damaged_roof),
                               worst_facade=fmt(c.worst_facade_damage),
                               damage_lower_third=fmt(c.damage_by_third[0] if c.damage_by_third else None))
                    if b:
                        out.update(floors=b.floors, height_m=fmt(b.height_m, 1), width_m=fmt(b.width_m, 1),
                                   structure=b.structure_type, consequence_class=b.consequence_class)
                    if d:
                        out.update(damage_category=d.damage_category, condition_category=d.condition_category,
                                   confidence=d.confidence, escalation=d.escalation)
                    if k:
                        out.update(cost_low=round(k.low), cost_high=round(k.high))
                    out["error"] = "; ".join(r.errors)
                except Exception as e:      # a crashed case is recorded, the run goes on (task 9.3.3)
                    log.error("case %s failed:\n%s", row["case_id"], traceback.format_exc())
                    out["error"] = f"{type(e).__name__}: {e}"
                out["seconds"] = round(time.time() - t, 1)
                w.writerow(out)
                f.flush()
                log.info("run %d case %s done in %.1fs", run, row["case_id"], out["seconds"])
    print(f"results: {args.out}")


if __name__ == "__main__":
    main()
