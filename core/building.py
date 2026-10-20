"""Building dimensions from a mask and a known height (task 4.4), and the consequence class estimate.

Segmentation gives pixels; one real size is needed to turn them into metres. That size is the height
(floors x floor height, or a reference object). Scale = height in metres / height in pixels, then
width = width in pixels x scale. Depth: in a set of views from different sides, the narrowest facade is
the end wall; with fewer views it cannot be seen and is assumed equal to width.

Everything here works on the main building only (main_building): the segmentation marks every building
in the frame, and a neighbour would otherwise be measured as part of ours.
"""
from collections import deque

import numpy as np
from PIL import Image

from core import config
from core.types import Cls

FACADE_CLASSES = [Cls.FACADE, Cls.DAMAGED_FACADE, Cls.BROKEN_WINDOW]


def _components(grid: np.ndarray) -> np.ndarray:
    """4-connected labels of a small boolean grid (0 = none). Plain BFS: the grid is ~200 px wide."""
    labels = np.zeros(grid.shape, np.int32)
    h, w = grid.shape
    n = 0
    for y, x in zip(*np.nonzero(grid)):
        if labels[y, x]:
            continue
        n += 1
        labels[y, x] = n
        queue = deque([(y, x)])
        while queue:
            cy, cx = queue.popleft()
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < h and 0 <= nx < w and grid[ny, nx] and not labels[ny, nx]:
                    labels[ny, nx] = n
                    queue.append((ny, nx))
    return labels


def main_building(mask: np.ndarray, grid: int | None = None, gap: float | None = None) -> np.ndarray:
    """Boolean mask of the building being assessed: the largest connected building region, favouring the
    one nearer the centre of the frame. Parts closer than `gap` (share of the frame size) are joined first,
    so a building split by a collapse or a tree stays one building. Other buildings are left out."""
    grid = grid or config.get("geometry", "main_building_grid")
    gap = gap if gap is not None else config.get("geometry", "main_building_gap")
    building = mask > 0
    if not building.any():
        return building
    h, w = mask.shape
    scale = grid / max(h, w)
    gh, gw = max(1, round(h * scale)), max(1, round(w * scale))
    small = np.asarray(Image.fromarray(building.astype(np.uint8) * 255).resize((gw, gh), Image.BOX)) > 32
    r = max(1, round(gap * grid / 2))
    grown = small.copy()                      # dilate by r cells: gaps up to 2r are bridged
    for _ in range(r):
        g = grown.copy()
        g[1:, :] |= grown[:-1, :]
        g[:-1, :] |= grown[1:, :]
        g[:, 1:] |= grown[:, :-1]
        g[:, :-1] |= grown[:, 1:]
        grown = g
    labels = _components(grown)
    if labels.max() <= 1:
        return building
    ys, xs = np.indices(labels.shape)
    centre, half_diag = np.array([gh / 2, gw / 2]), np.hypot(gh, gw) / 2
    best, best_score = 0, -1.0
    for n in range(1, labels.max() + 1):
        part = (labels == n) & small
        area = part.sum()
        if area == 0:
            continue
        dist = np.hypot(ys[part].mean() - centre[0], xs[part].mean() - centre[1]) / half_diag
        score = area * (1 - 0.5 * dist)
        if score > best_score:
            best, best_score = n, score
    keep = np.asarray(Image.fromarray((labels == best).astype(np.uint8) * 255).resize((w, h), Image.NEAREST)) > 0
    return building & keep


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


def facade_aspect(mask: np.ndarray) -> float | None:
    """Facade width / facade height in pixels: times the building height it gives the facade width in metres
    seen in this view, whatever the distance of the camera."""
    h_px, w_px = facade_extent_px(mask)
    return w_px / h_px if h_px > 0 else None


def depth_from_views(masks: list[np.ndarray], height_m: float, width_m: float) -> float | None:
    """Depth from views of different sides: the narrowest facade among them is taken as the end wall.
    None when there are fewer than [geometry] depth_min_views views showing enough facade."""
    min_share = config.get("suitability", "min_facade_share")
    widths = [a * height_m for m in masks
              if np.isin(m, FACADE_CLASSES).mean() >= min_share and (a := facade_aspect(m))]
    if len(widths) < config.get("geometry", "depth_min_views"):
        return None
    # a view cut off at the frame edge also looks narrow: never below a third of the width
    return max(min(min(widths), width_m), width_m / 3)


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
