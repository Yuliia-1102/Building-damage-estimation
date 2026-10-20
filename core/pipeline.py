"""assess(case) -> Report: the single entry point used by both the UI and the command line.

It runs in two stages so that editing a building parameter does not re-run the model (task 4.5):
  segment_case(case)  - the expensive part: segmentation and per-frame metrics, done once per case
  evaluate(seg, ...)  - the cheap part: dimensions, areas, decision, cost; re-run on every edit
"""
import logging
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from core import geometry, metrics
from core.building import main_building
from core.imageio import load_image
from core.interfaces import BuildingParamsEstimator, DecisionLayer, PriceSource, SegmentationModel
from core.types import BuildingParams, Case, FrameMetrics, Report, View

log = logging.getLogger(__name__)

Progress = Callable[[int, int, str], None]   # (done, total, what is happening)


@dataclass
class Segmentation:
    case: Case
    images: dict[int, np.ndarray] = field(default_factory=dict, repr=False)
    masks: dict[int, np.ndarray] = field(default_factory=dict, repr=False)     # main building only
    excluded: dict[int, np.ndarray] = field(default_factory=dict, repr=False)  # other buildings, not assessed
    frames: list[FrameMetrics] = field(default_factory=list)
    skipped: dict[int, str] = field(default_factory=dict)     # view_id -> error


def segment_view(view: View, segmenter: SegmentationModel) -> tuple[np.ndarray, np.ndarray]:
    image = load_image(view.image_path)
    if hasattr(segmenter, "predict_path"):
        mask = segmenter.predict_path(view.image_path)
    else:
        mask = segmenter.predict(image)
    if mask.shape != image.shape[:2]:
        raise ValueError(f"mask {mask.shape} does not match image {image.shape[:2]}")
    return image, mask


def segment_case(case: Case, segmenter: SegmentationModel, progress: Progress | None = None) -> Segmentation:
    seg = Segmentation(case=case)
    total = len(case.views)
    for i, view in enumerate(case.views):
        if progress:
            progress(i, total, f"segmenting view {view.view_id} of {total}")
        try:
            image, mask = segment_view(view, segmenter)
        except Exception as e:   # one bad frame must not kill the run (task 1.6)
            log.warning("view %d (%s) skipped: %s", view.view_id, view.image_path.name, e)
            seg.skipped[view.view_id] = str(e)
            continue
        # only the building being assessed: neighbours in the frame are not measured (core/building.py)
        main = main_building(mask)
        seg.excluded[view.view_id] = (mask > 0) & ~main
        mask = np.where(main, mask, 0).astype(mask.dtype)
        seg.images[view.view_id] = image
        seg.masks[view.view_id] = mask
        seg.frames.append(metrics.frame_metrics(view.view_id, mask))
        log.info("view %d segmented", view.view_id)
    if progress:
        progress(total, total, "segmentation done")
    return seg


def evaluate(seg: Segmentation,
             building: BuildingParams | None = None,
             building_estimator: BuildingParamsEstimator | None = None,
             decision_layer: DecisionLayer | None = None,
             price_source: PriceSource | None = None) -> Report:
    """Everything after segmentation. Pass `building` to use parameters the user corrected."""
    report = Report(
        case_id=seg.case.case_id,
        mode=seg.case.mode,
        views_assessed=len(seg.frames),
        frames=seg.frames,
        ratios=metrics.combine(seg.frames),
        skipped_frames=seg.skipped,
        masks=seg.masks,
        excluded=seg.excluded,
    )
    log.info("combined ratios: %s", report.ratios)

    if building is None and building_estimator is not None and seg.frames:
        ids = [f.view_id for f in seg.frames]
        try:
            building = building_estimator.estimate([seg.images[i] for i in ids], [seg.masks[i] for i in ids])
            log.info("building parameters estimated: %s", building)
        except Exception as e:   # a failed step is reported, the rest of the report is still produced
            if getattr(e, "pending", False):    # answer requested from a subagent: the decision needs it
                report.errors.append(f"building parameters: {e}")
                return report
            log.exception("building parameters failed")
            report.errors.append(f"building parameters: {e}")
    report.building = building

    if building is not None and building.width_m is not None and building.height_m is not None:
        report.areas = geometry.damaged_areas(report.ratios, building, seg.frames)
        log.info("damaged areas: %s", report.areas)

    if decision_layer is not None and seg.frames:
        try:
            views = {i: (seg.images[i], seg.masks[i]) for i in (f.view_id for f in seg.frames)}
            report.decision = decision_layer.decide(report.ratios, report.areas, report.building, views=views)
            log.info("decision: %s", report.decision)
        except Exception as e:
            if not getattr(e, "pending", False):
                log.exception("decision layer failed")
            report.errors.append(f"decision layer: {e}")

    if price_source is not None and report.decision is not None:
        from core.cost import estimate_cost
        report.cost = estimate_cost(report.decision.works, price_source, report.views_assessed)
        log.info("cost: %s", report.cost)
    return report


def assess(case: Case,
           segmenter: SegmentationModel,
           building_estimator: BuildingParamsEstimator | None = None,
           decision_layer: DecisionLayer | None = None,
           price_source: PriceSource | None = None,
           progress: Progress | None = None) -> Report:
    seg = segment_case(case, segmenter, progress)
    return evaluate(seg, building_estimator=building_estimator, decision_layer=decision_layer,
                    price_source=price_source)
