"""Building dimensions from a mask and a known height (task 4.4), and the consequence class estimate.

Segmentation gives pixels; one real size is needed to turn them into metres. That size is the height
(floors x floor height, or a reference object). Scale = height in metres / height in pixels, then
width = width in pixels x scale. Depth cannot be seen in a frontal view and is assumed equal to width.
"""
import numpy as np

from core import config
from core.types import Cls

FACADE_CLASSES = [Cls.FACADE, Cls.DAMAGED_FACADE, Cls.BROKEN_WINDOW]


def facade_extent_px(mask: np.ndarray, percentile: float | None = None) -> tuple[float, float]:
    """(height, width) of the facade in pixels.

    Height: a high percentile of per-column facade heights, so a tree in front of part of the wall or a
    sloping roofline does not decide it. Width: the same over per-row widths.
    """
    if percentile is None:
        percentile = config.get("geometry", "mask_extent_percentile")
    facade = np.isin(mask, FACADE_CLASSES)
    col_heights = facade.sum(axis=0)
    row_widths = facade.sum(axis=1)
    cols = col_heights[col_heights > 0]
    rows = row_widths[row_widths > 0]
    if cols.size == 0:
        return 0.0, 0.0
    return float(np.percentile(cols, percentile)), float(np.percentile(rows, percentile))


def frames_for_floors(masks: list[np.ndarray]) -> list[int]:
    """Frame indices, the one showing the most facade first: floors are counted on it (task 4.2.2).
    The next ones are tried when the floors cannot be read on the first (a close-up of a wall, say)."""
    return [int(i) for i in np.argsort([-np.isin(m, FACADE_CLASSES).mean() for m in masks], kind="stable")]


def best_frame_for_floors(masks: list[np.ndarray]) -> int:
    return frames_for_floors(masks)[0]


def width_from_height(mask: np.ndarray, height_m: float) -> tuple[float | None, float]:
    """(width in metres, scale in metres per pixel) from a known facade height."""
    h_px, w_px = facade_extent_px(mask)
    if h_px == 0:
        return None, 0.0
    scale = height_m / h_px
    return w_px * scale, scale


def height_from_reference(mask: np.ndarray, ref_height_m: float, ref_height_px: float) -> float | None:
    """Building height from an object of known size standing near the facade (task 4.3)."""
    h_px, _ = facade_extent_px(mask)
    if ref_height_px <= 0 or h_px == 0:
        return None
    return h_px * ref_height_m / ref_height_px


def consequence_class(floors: int | None, width_m: float | None, depth_m: float | None) -> tuple[int | None, str | None]:
    """(estimated occupants, CC1/CC2/CC3) by ДБН В.1.2-14:2018 table 1, people staying permanently.

    Occupants = gross floor area / area per person. A rough team estimate for ordering inspections only;
    the official class is set under ДСТУ 8855:2019.
    """
    if floors is None or width_m is None:
        return None, None
    area = floors * width_m * (depth_m if depth_m is not None else width_m)
    people = int(area / config.get("geometry", "floor_area_per_person_m2"))
    if people > 400:
        return people, "CC3"
    if people > 50:
        return people, "CC2"
    return people, "CC1"
