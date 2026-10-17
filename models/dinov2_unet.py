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


class QuickSegmenter:
    """The same model in one pass over the frame shrunk to a single 518 px crop (~5 s on CPU instead of 10-60 s).
    Too coarse for measuring damage; good enough to tell whether a video frame shows the building whole,
    which is what view selection needs (core/video.py). Shares the loaded weights with `full`."""

    def __init__(self, full: DinoV2Segmenter):
        self.full = full

    def predict(self, image: np.ndarray) -> np.ndarray:
        import torch
        from models.damage_seg import PATCH, DamageSegmenter
        if self.full._seg is None:
            self.full._seg = DamageSegmenter(self.full.weights, device=self.full.device)
        seg = self.full._seg
        small = Image.fromarray(image).convert("RGB").resize((PATCH, PATCH))
        with torch.no_grad():
            emb = seg.embedder(seg._embed_tf(small)[None].to(seg.device))
            logits = seg.model(seg._crop_tf(small)[None].to(seg.device), emb, torch.zeros(1, 2, device=seg.device))
        mask = logits[0].argmax(0).cpu().numpy().astype(np.uint8)
        return np.asarray(Image.fromarray(mask).resize((image.shape[1], image.shape[0]), Image.NEAREST))
