"""The trained damage model (DINOv2-Emb U-Net, paper DOI 10.1080/08839514.2026.2685357) behind
the SegmentationModel interface. The model itself lives unchanged in damage_seg.py."""
from pathlib import Path

import numpy as np
from PIL import Image

from core import config


class DinoV2Segmenter:
    """Loads the weights (~15 s) on the first predict, so a run served fully from cache skips it."""

    def __init__(self, weights: Path | None = None, device: str | None = None):
        self.weights = Path(weights) if weights else config.path("weights")
        if not self.weights.exists():
            raise FileNotFoundError(f"segmentation weights not found at {self.weights}, see README")
        self.device = device
        self._seg = None

    def predict(self, image: np.ndarray, progress=None) -> np.ndarray:
        """Class ids match core.types.Cls one to one (0 Other ... 5 Damaged roof)."""
        if self._seg is None:
            from models.damage_seg import DamageSegmenter   # torch is imported only when needed
            self._seg = DamageSegmenter(self.weights, device=self.device)
        probs = self._seg.predict_probs(Image.fromarray(image), progress=progress)
        return probs.argmax(-1).astype(np.uint8)
