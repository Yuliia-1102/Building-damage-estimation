"""Saving per-view masks and overlays to disk (task 2.5)."""
import json
from pathlib import Path

from PIL import Image

from core.imageio import LEGEND, colorize, overlay


def save_views(seg, out_dir: Path) -> list[Path]:
    """For each view: <id>_mask.png (pixel value = class id), <id>_color.png and <id>_overlay.jpg."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for view_id, mask in seg.masks.items():
        stem = f"view{view_id}"
        Image.fromarray(mask).save(out_dir / f"{stem}_mask.png")
        Image.fromarray(colorize(mask)).save(out_dir / f"{stem}_color.png")
        Image.fromarray(overlay(seg.images[view_id], mask)).save(out_dir / f"{stem}_overlay.jpg", quality=90)
        written.append(out_dir / f"{stem}_overlay.jpg")
    (out_dir / "legend.json").write_text(json.dumps(LEGEND, indent=2), encoding="utf-8")
    return written
