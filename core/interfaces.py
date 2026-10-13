"""The replaceable components. The core only talks to these, never to a concrete model or database."""
from datetime import date
from typing import Protocol

import numpy as np

from core.types import BuildingParams, CombinedRatios, DamagedAreas, Decision


class SegmentationModel(Protocol):
    def predict(self, image: np.ndarray) -> np.ndarray:
        """HxWx3 uint8 RGB image -> HxW uint8 mask with values from core.types.Cls."""
        ...


class BuildingParamsEstimator(Protocol):
    def estimate(self, images: list[np.ndarray], masks: list[np.ndarray]) -> BuildingParams:
        """Floor count, height, width, depth. Masks are passed so the building's pixel size can be measured."""
        ...


class DecisionLayer(Protocol):
    def decide(self, ratios: CombinedRatios, areas: DamagedAreas | None,
               building: BuildingParams | None) -> Decision:
        """Numbers in, structured answer out. No arithmetic on prices here."""
        ...


class PriceSource(Protocol):
    def get_items_by_work_type(self, work_type: str, limit: int) -> list[dict]:
        """Catalogue items suitable for a work type: dicts with at least id, name, unit."""
        ...

    def get_price_as_of(self, item_id: int, as_of: date) -> float:
        ...
