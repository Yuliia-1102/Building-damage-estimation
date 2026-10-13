"""Read the CVAT 1.1 XML export and rasterise it into 6-class masks.

Usage:
    python -m tools.cvat <annotations.xml> <out_dir>

CVAT labels map to our classes as below. Almost every shape has z_order=0, so overlap is
resolved by class priority instead: later entries in PAINT_ORDER are drawn on top.
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from core.types import Cls

LABEL_TO_CLASS = {
    "Other": Cls.BACKGROUND,          # occluders and surroundings
    "Building": Cls.FACADE,
    "Roof": Cls.ROOF,
    "Damage": Cls.DAMAGED_FACADE,
    "Broken Window": Cls.BROKEN_WINDOW,
    "Damaged roof": Cls.DAMAGED_ROOF,
}

# Base surfaces first, occluders over them, damage on top.
PAINT_ORDER = ["Building", "Roof", "Other", "Damage", "Damaged roof", "Broken Window"]


def _paint_shape(canvas: Image.Image, shape: ET.Element, value: int) -> None:
    draw = ImageDraw.Draw(canvas)
    if shape.tag == "polygon":
        pts = [tuple(map(float, p.split(","))) for p in shape.get("points").split(";")]
        if len(pts) >= 3:
            draw.polygon(pts, fill=value)
    elif shape.tag == "box":
        draw.rectangle([float(shape.get(k)) for k in ("xtl", "ytl", "xbr", "ybr")], fill=value)
    elif shape.tag == "mask":
        left, top = int(shape.get("left")), int(shape.get("top"))
        w, h = int(shape.get("width")), int(shape.get("height"))
        runs = [int(x) for x in shape.get("rle").split(",")]
        flat = np.zeros(w * h, dtype=bool)
        pos = 0
        for i, run in enumerate(runs):      # runs alternate: background, foreground, ...
            if i % 2 == 1:
                flat[pos:pos + run] = True
            pos += run
        patch = Image.fromarray(flat.reshape(h, w).astype(np.uint8) * 255)
        canvas.paste(value, (left, top), patch)


def rasterize(image_el: ET.Element) -> np.ndarray:
    w, h = int(image_el.get("width")), int(image_el.get("height"))
    canvas = Image.new("L", (w, h), int(Cls.BACKGROUND))
    shapes = [s for s in image_el if s.tag in ("polygon", "box", "mask") and s.get("label") in LABEL_TO_CLASS]
    shapes.sort(key=lambda s: (int(s.get("z_order", 0)), PAINT_ORDER.index(s.get("label"))))
    for s in shapes:
        _paint_shape(canvas, s, int(LABEL_TO_CLASS[s.get("label")]))
    return np.asarray(canvas, dtype=np.uint8)


def load_masks(xml_path: Path) -> dict[str, np.ndarray]:
    """Image file name -> mask, for every annotated image."""
    root = ET.parse(xml_path).getroot()
    return {img.get("name"): rasterize(img) for img in root.iter("image")}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("xml", type=Path)
    p.add_argument("out_dir", type=Path)
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    root = ET.parse(args.xml).getroot()
    n = 0
    for img in root.iter("image"):
        mask = rasterize(img)
        Image.fromarray(mask).save(args.out_dir / (Path(img.get("name")).stem + ".png"))
        n += 1
    print(f"wrote {n} masks to {args.out_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
