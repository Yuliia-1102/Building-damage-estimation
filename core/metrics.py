"""Masks -> damage ratios (epic 3, tasks 3.1-3.4)."""
import numpy as np

from core import config
from core.types import NUM_CLASSES, Cls, CombinedRatios, FrameMetrics


def count_pixels(mask: np.ndarray) -> list[int]:
    """Pixels of each class; index = Cls value (task 3.1)."""
    return np.bincount(mask.ravel(), minlength=NUM_CLASSES)[:NUM_CLASSES].tolist()


def surface_pixels(counts: list[int]) -> tuple[int, int]:
    """Denominators (task 3.2): visible facade and visible roof."""
    facade = counts[Cls.FACADE] + counts[Cls.DAMAGED_FACADE] + counts[Cls.BROKEN_WINDOW]
    roof = counts[Cls.ROOF] + counts[Cls.DAMAGED_ROOF]
    return facade, roof


def _ratio(num: int, den: int) -> float | None:
    return num / den if den > 0 else None


def frame_metrics(view_id: int, mask: np.ndarray,
                  min_facade_share: float | None = None,
                  min_roof_share: float | None = None) -> FrameMetrics:
    """Ratios for one frame plus whether it is usable for facade and for roof (task 3.3)."""
    if min_facade_share is None:
        min_facade_share = config.get("suitability", "min_facade_share")
    if min_roof_share is None:
        min_roof_share = config.get("suitability", "min_roof_share")

    counts = count_pixels(mask)
    facade_px, roof_px = surface_pixels(counts)
    total = mask.size
    facade_share = facade_px / total
    roof_share = roof_px / total

    reasons = []
    facade_usable = facade_share >= min_facade_share
    if not facade_usable:
        reasons.append(f"facade: {facade_share:.1%} of frame < {min_facade_share:.1%}")
    roof_usable = roof_share >= min_roof_share
    if not roof_usable:
        reasons.append(f"roof: {roof_share:.1%} of frame < {min_roof_share:.1%}")

    return FrameMetrics(
        view_id=view_id,
        counts=counts,
        facade_px=facade_px,
        roof_px=roof_px,
        facade_share=facade_share,
        roof_share=roof_share,
        damaged_facade_ratio=_ratio(counts[Cls.DAMAGED_FACADE], facade_px),
        broken_window_ratio=_ratio(counts[Cls.BROKEN_WINDOW], facade_px),
        damaged_roof_ratio=_ratio(counts[Cls.DAMAGED_ROOF], roof_px),
        facade_usable=facade_usable,
        roof_usable=roof_usable,
        excluded_reasons=reasons,
    )


def combine(frames: list[FrameMetrics]) -> CombinedRatios:
    """Whole-building ratios as a division of sums over usable frames (task 3.4).

    Equivalent to averaging per-frame ratios weighted by visible surface pixels, so the same
    damage seen in two frames adds to both numerator and denominator and is not counted twice.
    """
    facade = [f for f in frames if f.facade_usable]
    roof = [f for f in frames if f.roof_usable]

    facade_den = sum(f.facade_px for f in facade)
    roof_den = sum(f.roof_px for f in roof)

    return CombinedRatios(
        damaged_facade=_ratio(sum(f.counts[Cls.DAMAGED_FACADE] for f in facade), facade_den),
        broken_window=_ratio(sum(f.counts[Cls.BROKEN_WINDOW] for f in facade), facade_den),
        damaged_roof=_ratio(sum(f.counts[Cls.DAMAGED_ROOF] for f in roof), roof_den),
        facade_views=len(facade),
        roof_views=len(roof),
    )
