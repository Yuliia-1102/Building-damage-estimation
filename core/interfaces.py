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
               building: BuildingParams | None, views: dict | None = None) -> Decision:
        """Numbers (and optionally the views: view_id -> (image, mask)) in, structured answer out.
        No arithmetic on prices here."""
        ...


class PriceSource(Protocol):
    """Mirrors the materials database: work_type, material, work_material, price (with history)."""

    def get_items_by_work_type(self, work_type: str, limit: int) -> list[dict]:
        """Materials used by a work type: dicts with id, name, unit, quantity_per_unit (per 1 unit of work)."""
        ...

    def get_price_as_of(self, item_id: int, as_of: date) -> tuple[float, str] | None:
        """(price per unit, date the price is valid from) for the latest price on or before as_of."""
        ...

    def get_labour_price_as_of(self, work_type: str, as_of: date) -> tuple[float, str] | None:
        """Labour price per unit of work, if the source has one."""
        ...
