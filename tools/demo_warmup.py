"""Warm the Gemini cache for the demo scenes (docs/demo_scenario.md) exactly as the UI asks: same images,
same prompts. Paid: about 5-8 requests the first time, none after (each line says whether it sent one).

    uv run python -m tools.demo_warmup
"""
import copy
import glob
import logging
from pathlib import Path

from core import config
from core.cache import CachedSegmenter, quick_segmenter
from core.case import case_from_paths, case_from_video
from core.pipeline import evaluate, segment_case
from models.dinov2_unet import DinoV2Segmenter
from models.gemini_building import GeminiBuildingEstimator, recompute
from models.gemini_decision import GeminiDecisionLayer
from models.price_source import default_price_source

DATASET = config.ROOT.parent / "Dataset_CVAT" / "images" / "default"
PHOTO_SET = config.ROOT.parent / "videos" / "photo_sets" / "download12_2"
VIDEO = config.ROOT.parent / "videos" / "corpus" / "download11_5_half.mp4"


def source(layer) -> str:
    return "cache" if layer.llm.last_from_cache else "NEW REQUEST"


def line(scene: str, r) -> str:
    return (f"{scene}: floors {r.building.floors}, {r.building.structure_type}, "
            f"{r.decision.damage_category} / {r.decision.condition_category}, "
            f"{r.cost.low:,.0f}-{r.cost.high:,.0f} UAH")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    seg_model = CachedSegmenter(DinoV2Segmenter(), config.path("weights").stem)
    building, decision = GeminiBuildingEstimator(), GeminiDecisionLayer()

    # scene 1: one photo
    seg = segment_case(case_from_paths("download10", [DATASET / "download10.png"]), seg_model)
    r = evaluate(seg, building_estimator=building, decision_layer=decision, price_source=default_price_source())
    print(line("scene 1", r), "| building", source(building), "| decision", source(decision))

    # scene 2: photo set; scene 4: the same report with floors 5 -> 6
    paths = sorted(Path(p) for p in glob.glob(str(PHOTO_SET / "*.jpg")))
    seg = segment_case(case_from_paths("download12_2", paths), seg_model)
    r = evaluate(seg, building_estimator=building, decision_layer=decision, price_source=default_price_source())
    print(line("scene 2", r), "| building", source(building), "| decision", source(decision))
    edited = copy.deepcopy(r.building)
    edited.floors = r.building.floors + 1
    masks = [seg.masks[f.view_id] for f in seg.frames]
    edited = recompute(edited, masks[edited.source_frame], {"floors"})
    r = evaluate(seg, building=edited, decision_layer=decision, price_source=default_price_source())
    print(line("scene 4", r), "| decision", source(decision))

    # scene 3: video (the UI extracts the same frames, so its answers come from this cache)
    case, _ = case_from_video(VIDEO, config.path("cases") / "_video", quick_segmenter(seg_model))
    seg = segment_case(case, seg_model)
    r = evaluate(seg, building_estimator=building, decision_layer=decision, price_source=default_price_source())
    print(line("scene 3", r), "| building", source(building), "| decision", source(decision))


if __name__ == "__main__":
    main()
