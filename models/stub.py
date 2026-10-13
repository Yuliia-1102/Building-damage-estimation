"""Implementations used when the real components are not available: tests, CI, development."""
from pathlib import Path

import numpy as np
from PIL import Image

from core import config
from core.types import BuildingParams, Cls, CombinedRatios, DamagedAreas, Decision


class StubSegmenter:
    """Top quarter roof, rest facade, a damaged block in the middle. No weights needed."""

    def predict(self, image: np.ndarray) -> np.ndarray:
        h, w = image.shape[:2]
        mask = np.full((h, w), Cls.FACADE, dtype=np.uint8)
        mask[: h // 4] = Cls.ROOF
        mask[h // 2: h // 2 + h // 8, w // 4: w // 2] = Cls.DAMAGED_FACADE
        return mask


class MaskFolderSegmenter:
    """Returns ready-made masks from a folder (e.g. rasterised CVAT annotations), matched by file name.

    Lets the metrics pipeline run on ground truth before the trained model is connected.
    Needs the file name, so it implements predict_path; the pipeline prefers it when present.
    """

    def __init__(self, mask_dir: Path):
        self.mask_dir = Path(mask_dir)

    def predict_path(self, image_path: Path) -> np.ndarray:
        return np.asarray(Image.open(self.mask_dir / (Path(image_path).stem + ".png")), dtype=np.uint8)

    def predict(self, image: np.ndarray) -> np.ndarray:
        raise NotImplementedError("MaskFolderSegmenter needs the file name, use predict_path")


class StubBuildingParams:
    """Fixed 5-storey 20 x 12 m building until epic 4 is ready."""

    def estimate(self, images, masks) -> BuildingParams:
        return BuildingParams(
            floors=5,
            floor_height_m=config.get("geometry", "default_floor_height_m"),
            width_m=20.0,
            depth_m=12.0,
            roof_shape_coef=config.get("geometry", "roof_shape_coef_flat"),
            assumptions=["stub building parameters, not detected"],
        )


class StubDecisionLayer:
    def decide(self, ratios: CombinedRatios, areas: DamagedAreas | None, building) -> Decision:
        return Decision(category="stub", confidence=0.0, works=[])
