"""Run assess() from the command line (task 1.5).

    python cli.py <folder or image> [--masks DIR | --stub] [--gemini] [--json]

By default the trained model is used (weights path in config.toml), with masks cached on disk.
--masks DIR uses ready-made masks (e.g. from tools/cvat.py), --stub a fake mask without weights.
--gemini sends paid Gemini requests (needs GEMINI_API_KEY); otherwise cached Gemini answers, or stubs.
"""
import argparse
import dataclasses
import json
import logging
from pathlib import Path

from core import cache, config
from core.case import case_from_folder
from core.output import save_views
from core.pipeline import evaluate, segment_case
from models.price_source import default_price_source
from core.types import Report
from models.stub import MaskFolderSegmenter, StubBuildingParams, StubDecisionLayer, StubSegmenter


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _m2(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} m2"


def _m(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} m"


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
    if c.worst_facade_damage is not None:
        print(f"Worst facade view: view {c.worst_facade_view}, {_pct(c.worst_facade_damage)} damaged")
    if c.worst_section_damage is not None:
        print(f"Worst facade section (a third of the width): view {c.worst_section_view}, "
              f"{_pct(c.worst_section_damage)} damaged")
    if c.damage_by_third:
        print("Facade damage by height: " + ", ".join(f"{n} {v:.0%}" for n, v in
                                                     zip(["lower", "middle", "upper"], c.damage_by_third)))
    if r.areas:
        a = r.areas
        print(f"Areas: walls {_m2(a.wall_area_m2)}, roof {_m2(a.roof_area_m2)}; damaged facade {_m2(a.damaged_facade_m2)}, "
              f"broken windows {_m2(a.broken_window_m2)}, damaged roof {_m2(a.damaged_roof_m2)}")
    if r.decision:
        d = r.decision
        if d.escalation == "insufficient_data":
            print(f"Assessment: INSUFFICIENT DATA (confidence {d.confidence:.2f}) - add photos from other sides "
                  f"or treat the building as unknown priority")
        else:
            flag = " (preliminary: do not lower its inspection priority)" if d.escalation == "preliminary" else ""
            print(f"Damage category {d.damage_category} ({d.damage_name}); technical condition "
                  f"{d.condition_category} ({d.condition_name}); confidence {d.confidence:.2f}{flag}")
        if d.roof_covering_category:
            print(f"  roof covering by damaged area (ДСТУ 9273 table В.7.1): category {d.roof_covering_category}")
        for w in d.works:
            print(f"  work: {w.work_type} - {_m2(w.quantity)}")
    if r.cost:
        k = r.cost
        print(f"Cost: {k.low:,.0f} - {k.high:,.0f} {k.currency} (point estimate {k.total:,.0f}, prices as of {k.as_of})")
        for w in k.skipped_works:
            print(f"  not priced: {w}")
    if r.building:
        b = r.building
        auto = lambda name: " (auto)" if name in b.auto_detected else ""
        print(f"Building: floors {b.floors}{auto('floors')}, height {_m(b.height_m)} [{b.height_source}], "
              f"width {_m(b.width_m)}{auto('width_m')}, depth {_m(b.depth_m)}{auto('depth_m')}, "
              f"structure {b.structure_type}{auto('structure_type')}, roof {b.roof_type}; "
              f"consequence class {b.consequence_class} (~{b.occupants_estimate} people, estimate)")
        if b.assumptions:
            print("Assumptions: " + "; ".join(b.assumptions))


def to_json(r: Report) -> str:
    d = dataclasses.asdict(dataclasses.replace(r, masks={}))
    d.pop("masks")
    return json.dumps(d, indent=2, ensure_ascii=False, default=list)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path, help="case folder, a single image, or a video")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--masks", type=Path, help="folder with ready-made masks instead of the model")
    src.add_argument("--stub", action="store_true", help="fake segmentation, no weights needed")
    p.add_argument("--gemini", action="store_true", help="real decision layer instead of the stub")
    p.add_argument("--no-cache", action="store_true", help="always run the model")
    p.add_argument("--clear-cache", action="store_true", help="delete cached masks and answers first")
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    p.add_argument("--save", type=Path, help="folder to save masks and overlays to")
    p.add_argument("--floors", type=int, help="correct the floor count; recalculates without re-segmenting")
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
        from models.gemini_building import GeminiBuildingEstimator
        from models.gemini_decision import GeminiDecisionLayer
        decision_layer = GeminiDecisionLayer(use_cache=not args.no_cache)
        building_estimator = GeminiBuildingEstimator(use_cache=not args.no_cache)
    elif args.stub or args.masks:
        decision_layer = StubDecisionLayer()
        building_estimator = StubBuildingParams()
    else:           # no requests: cached Gemini answers, stubs where nothing is cached
        from models.offline import CachedOrStubBuilding, CachedOrStubDecision
        decision_layer = CachedOrStubDecision()
        building_estimator = CachedOrStubBuilding()

    from core.video import VIDEO_EXTS
    if args.input.suffix.lower() in VIDEO_EXTS:
        from core.case import case_from_video
        quick = cache.quick_segmenter(segmenter) if isinstance(segmenter, cache.CachedSegmenter) else None
        case, info = case_from_video(args.input, config.path("cases") / "_video", quick)
        print(f"Video: {info['extracted']} frames, {info['blurred']} blurred, {info['checked']} candidates "
              f"checked, {info['selected']} views selected")
        for name, reason in info["rejected"].items():
            print(f"  rejected {name}: {reason}")
    else:
        case = case_from_folder(args.input)
    seg = segment_case(case, segmenter)
    if args.save:
        save_views(seg, args.save)
    prices = default_price_source()
    report = evaluate(seg, building_estimator=building_estimator, decision_layer=decision_layer,
                      price_source=prices)
    if args.floors is not None and report.building is not None:
        from core.building import best_frame_for_floors
        from models.gemini_building import recompute
        masks = [seg.masks[f.view_id] for f in seg.frames]
        report.building.floors = args.floors
        building = recompute(report.building, masks[report.building.source_frame if report.building.source_frame is not None else best_frame_for_floors(masks)], {"floors"})
        report = evaluate(seg, building=building, decision_layer=decision_layer, price_source=prices)
    if args.json:
        print(to_json(report))
    else:
        print_text(report)


if __name__ == "__main__":
    main()
