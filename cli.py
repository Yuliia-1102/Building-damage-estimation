"""Run assess() from the command line (task 1.5).

    python cli.py <folder or image> [--masks DIR] [--json]

--masks DIR uses ready-made masks (e.g. from tools/cvat.py) instead of the model.
"""
import argparse
import dataclasses
import json
import logging
from pathlib import Path

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
    if r.building and r.building.assumptions:
        print("Assumptions: " + "; ".join(r.building.assumptions))


def to_json(r: Report) -> str:
    d = dataclasses.asdict(dataclasses.replace(r, masks={}))
    d.pop("masks")
    return json.dumps(d, indent=2, ensure_ascii=False, default=list)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="case folder or a single image")
    p.add_argument("--masks", type=Path, help="folder with ready-made masks instead of the model")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    segmenter = MaskFolderSegmenter(args.masks) if args.masks else StubSegmenter()
    report = assess(case_from_folder(args.input), segmenter,
                    building_estimator=StubBuildingParams(), decision_layer=StubDecisionLayer())
    if args.json:
        print(to_json(report))
    else:
        print_text(report)


if __name__ == "__main__":
    main()
