"""The trained damage model (DINOv2-Emb U-Net, paper DOI 10.1080/08839514.2026.2685357) behind
the SegmentationModel interface. The model itself lives unchanged in damage_seg.py."""
from pathlib import Path

import numpy as np
from PIL import Image

from core import config


class DinoV2Segmenter:
    def __init__(self, weights: Path | None = None, device: str | None = None):
        from models.damage_seg import DamageSegmenter   # torch is imported only when the model is used

        weights = Path(weights) if weights else config.path("weights")
        if not weights.exists():
            raise FileNotFoundError(f"segmentation weights not found at {weights}, see README")
        self._seg = DamageSegmenter(weights, device=device)

    def predict(self, image: np.ndarray, progress=None) -> np.ndarray:
        """Class ids match core.types.Cls one to one (0 Other ... 5 Damaged roof)."""
        probs = self._seg.predict_probs(Image.fromarray(image), progress=progress)
        return probs.argmax(-1).astype(np.uint8)
