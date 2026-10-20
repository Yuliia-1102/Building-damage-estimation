"""Loading frames and drawing masks over them (tasks 2.4, 2.5)."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from core.types import Cls

# RGB per class, index = Cls value.
PALETTE = np.array([
    (0, 0, 0),        # background (not drawn)
    (40, 180, 70),    # facade: green
    (255, 140, 0),    # roof: orange
    (150, 40, 200),   # damaged facade: purple
    (30, 90, 255),    # broken window: blue
    (230, 25, 25),    # damaged roof: red
], dtype=np.uint8)

LEGEND = {c.name.lower().replace("_", " "): tuple(PALETTE[c].tolist()) for c in Cls}


def load_image(path: Path) -> np.ndarray:
    """RGB uint8, with EXIF rotation applied so phone photos are upright."""
    with Image.open(path) as im:
        return np.asarray(ImageOps.exif_transpose(im).convert("RGB"))


def colorize(mask: np.ndarray) -> np.ndarray:
    return PALETTE[mask]


def overlay(image: np.ndarray, mask: np.ndarray, alpha: float = 0.4,
            excluded: np.ndarray | None = None) -> np.ndarray:
    """Mask drawn over the photo, translucent so the photo stays visible under it; background left untouched.
    excluded: other buildings in the frame, greyed out to show they were not assessed."""
    out = image.astype(np.float32)
    fg = mask != Cls.BACKGROUND
    out[fg] = (1 - alpha) * out[fg] + alpha * colorize(mask)[fg]
    if excluded is not None and excluded.any():
        grey = out[excluded].mean(axis=1, keepdims=True)
        out[excluded] = 0.35 * grey + 0.65 * 150
    return out.astype(np.uint8)


def building_box(mask: np.ndarray, margin: float = 0.08) -> tuple[int, int, int, int]:
    """(top, bottom, left, right) of everything segmented as building, widened by `margin` of the frame size;
    the whole frame when nothing is segmented."""
    h, w = mask.shape
    rows, cols = np.flatnonzero((mask > 0).any(axis=1)), np.flatnonzero((mask > 0).any(axis=0))
    if rows.size == 0:
        return 0, h, 0, w
    dy, dx = int(margin * h), int(margin * w)
    return max(0, rows[0] - dy), min(h, rows[-1] + 1 + dy), max(0, cols[0] - dx), min(w, cols[-1] + 1 + dx)


def overlay_for_model(image: np.ndarray, mask: np.ndarray, alpha: float = 0.3) -> np.ndarray:
    """The mask for the language model: a light fill, so the photo under it stays readable, plus solid outlines
    of every region, so the boundaries are clear even where the fill is faint."""
    out = overlay(image, mask, alpha)
    edge = np.zeros(mask.shape, bool)
    edge[1:, :] |= mask[1:, :] != mask[:-1, :]
    edge[:, 1:] |= mask[:, 1:] != mask[:, :-1]
    for _ in range(max(1, min(mask.shape) // 400)):         # about 2-3 px at 1000 px
        grown = edge.copy()
        grown[1:, :] |= edge[:-1, :]
        grown[:, 1:] |= edge[:, :-1]
        edge = grown
    edge &= mask != Cls.BACKGROUND
    out[edge] = colorize(mask)[edge]
    return out
