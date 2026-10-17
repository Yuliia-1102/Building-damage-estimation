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


def overlay(image: np.ndarray, mask: np.ndarray, alpha: float = 0.4) -> np.ndarray:
    """Mask drawn over the photo, translucent so the photo stays visible under it; background left untouched."""
    out = image.astype(np.float32)
    fg = mask != Cls.BACKGROUND
    out[fg] = (1 - alpha) * out[fg] + alpha * colorize(mask)[fg]
    return out.astype(np.uint8)
