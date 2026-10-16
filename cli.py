"""Run assess() from the command line (task 1.5).

    python cli.py <folder or image> [--masks DIR | --stub] [--gemini] [--json]

By default the trained model is used (weights path in config.toml), with masks cached on disk.
--masks DIR uses ready-made masks (e.g. from tools/cvat.py), --stub a fake mask without weights.
--gemini uses the real decision layer (needs GEMINI_API_KEY), otherwise a fixed stub answer.
"""
import argparse
import dataclasses
import json
import logging
from pathlib import Path

from core import cache, config
from core.case import case_from_folder
from core.pipeline import assess
from core.types import Report
from models.stub import MaskFolderSegmenter, StubBuildingParams, StubDecisionLayer, StubSegmenter


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _m2(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} m2"


def print_text(r: Report) -> None:
    print(f"Case {r.case_id}  mode={r.mode}  views assessed={r.views_assessed}")
    for f in r.frames:
        flags = f"facade {'ok' if f.facade_usable else 'excluded'}, roof {'ok' if f.roof_usable else 'excluded'}"
        print(f"  view {f.view_id}: damaged facade {_pct(f.damaged_facade_ratio)}, "
              f"broken windows {_pct(f.broken_window_ratio)}, damaged roof {_pct(f.damaged_roof_ratio)}  [{flags}]")
    for vid, err in r.skipped_frames.items():
        print(f"  view {vid}: SKIPPED - {err}")
    c = r.ratios
    print(f"Combined: damaged facade {_pct(c.damaged_facade)}, broken windows {_pct(c.broken_window)} "
          f"(over {c.facade_views} views), damaged roof {_pct(c.damaged_roof)} (over {c.roof_views} views)")
    if r.areas:
        a = r.areas
        print(f"Areas: walls {_m2(a.wall_area_m2)}, roof {_m2(a.roof_area_m2)}; damaged facade {_m2(a.damaged_facade_m2)}, "
              f"broken windows {_m2(a.broken_window_m2)}, damaged roof {_m2(a.damaged_roof_m2)}")
    if r.decision:
        d = r.decision
        if d.escalation == "not_classified":
            print(f"Condition: NOT CLASSIFIED (confidence {d.confidence:.2f} too low) - inspection by an engineer required")
        else:
            flag = " - inspection by an engineer recommended" if d.escalation == "inspect" else ""
            print(f"Condition: category {d.category} ({d.category_name}), confidence {d.confidence:.2f}{flag}")
        for w in d.works:
            print(f"  work: {w.work_type} - {_m2(w.quantity)}")
    if r.building and r.building.assumptions:
        print("Assumptions: " + "; ".join(r.building.assumptions))


def to_json(r: Report) -> str:
    d = dataclasses.asdict(dataclasses.replace(r, masks={}))
    d.pop("masks")
    return json.dumps(d, indent=2, ensure_ascii=False, default=list)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="case folder or a single image")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--masks", type=Path, help="folder with ready-made masks instead of the model")
    src.add_argument("--stub", action="store_true", help="fake segmentation, no weights needed")
    p.add_argument("--gemini", action="store_true", help="real decision layer instead of the stub")
    p.add_argument("--no-cache", action="store_true", help="always run the model")
    p.add_argument("--clear-cache", action="store_true", help="delete cached masks and answers first")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    if args.clear_cache:
        cache.clear()

    if args.masks:
        segmenter = MaskFolderSegmenter(args.masks)
    elif args.stub:
        segmenter = StubSegmenter()
    else:
        from models.dinov2_unet import DinoV2Segmenter
        segmenter = DinoV2Segmenter()
        if not args.no_cache:
            segmenter = cache.CachedSegmenter(segmenter, model_id=config.path("weights").stem)

    if args.gemini:
        from models.gemini_decision import GeminiDecisionLayer
        decision_layer = GeminiDecisionLayer(use_cache=not args.no_cache)
    else:
        decision_layer = StubDecisionLayer()

    report = assess(case_from_folder(args.input), segmenter,
                    building_estimator=StubBuildingParams(), decision_layer=decision_layer)
    if args.json:
        print(to_json(report))
    else:
        print_text(report)


if __name__ == "__main__":
    main()
