"""On-disk cache for model outputs (task 2.6): masks by image content, decision responses by prompt.

The key is a hash of the file content, not its name, so a renamed copy is still a hit and an
edited photo is a miss. Delete the cache folder (or use cli.py --clear-cache) to reset it.
"""
import hashlib
import json
import logging
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from core import config
from core.imageio import load_image

log = logging.getLogger(__name__)


def cache_dir() -> Path:
    return config.path("cache")


def clear() -> None:
    shutil.rmtree(cache_dir(), ignore_errors=True)


def file_key(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CachedSegmenter:
    """Wraps any SegmentationModel; the model runs only on images it has not seen before."""

    def __init__(self, inner, model_id: str, root: Path | None = None):
        self.inner = inner
        self.dir = (root or cache_dir()) / "masks" / model_id
        self.hits = 0
        self.misses = 0

    def predict_path(self, image_path: Path) -> np.ndarray:
        path = self.dir / f"{file_key(image_path)}.png"
        if path.exists():
            self.hits += 1
            log.info("mask cache hit for %s", Path(image_path).name)
            return np.asarray(Image.open(path), dtype=np.uint8)
        self.misses += 1
        mask = self.inner.predict(load_image(image_path))
        self.dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray(mask).save(path)
        return mask

    def predict(self, image: np.ndarray) -> np.ndarray:
        return self.inner.predict(image)


def quick_segmenter(full: CachedSegmenter):
    """The cached quick segmenter (view selection) sharing the weights of a cached DinoV2Segmenter."""
    from models.dinov2_unet import QuickSegmenter
    return CachedSegmenter(QuickSegmenter(full.inner), model_id=full.dir.name + "_quick518")


def get_json(namespace: str, key: str, root: Path | None = None) -> dict | None:
    path = (root or cache_dir()) / namespace / f"{key}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def put_json(namespace: str, key: str, value: dict, root: Path | None = None) -> None:
    path = (root or cache_dir()) / namespace / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
