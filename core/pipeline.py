"""assess(case) -> Report: the single entry point used by both the UI and the command line."""
import logging

import numpy as np

from core import geometry, metrics
from core.imageio import load_image
from core.interfaces import BuildingParamsEstimator, DecisionLayer, PriceSource, SegmentationModel
from core.types import Case, Report, View

log = logging.getLogger(__name__)


def segment_view(view: View, segmenter: SegmentationModel) -> tuple[np.ndarray, np.ndarray]:
    image = load_image(view.image_path)
    if hasattr(segmenter, "predict_path"):
        mask = segmenter.predict_path(view.image_path)
    else:
        mask = segmenter.predict(image)
    if mask.shape != image.shape[:2]:
        raise ValueError(f"mask {mask.shape} does not match image {image.shape[:2]}")
    return image, mask


def assess(case: Case,
           segmenter: SegmentationModel,
           building_estimator: BuildingParamsEstimator | None = None,
           decision_layer: DecisionLayer | None = None,
           price_source: PriceSource | None = None) -> Report:
    images, masks, frames, skipped = [], {}, [], {}

    for view in case.views:
        try:
            image, mask = segment_view(view, segmenter)
        except Exception as e:   # one bad frame must not kill the run (task 1.6)
            log.warning("view %d (%s) skipped: %s", view.view_id, view.image_path.name, e)
            skipped[view.view_id] = str(e)
            continue
        images.append(image)
        masks[view.view_id] = mask
        frames.append(metrics.frame_metrics(view.view_id, mask))
        log.info("view %d segmented", view.view_id)

    report = Report(
        case_id=case.case_id,
        mode=case.mode,
        views_assessed=len(frames),
        frames=frames,
        ratios=metrics.combine(frames),
        skipped_frames=skipped,
        masks=masks,
    )

    if building_estimator is not None and frames:
        report.building = building_estimator.estimate(images, list(masks.values()))
        report.areas = geometry.damaged_areas(report.ratios, report.building)

    if decision_layer is not None:
        report.decision = decision_layer.decide(report.ratios, report.areas, report.building)

    # Cost calculation (epic 6.5) goes here, using price_source.
    return report
