"""Data structures shared by every part of the system: case in, report out."""
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

import numpy as np


class Cls(IntEnum):
    """The six segmentation classes. A mask is an HxW uint8 array of these values."""
    BACKGROUND = 0
    FACADE = 1          # intact facade
    ROOF = 2            # intact roof
    DAMAGED_FACADE = 3
    BROKEN_WINDOW = 4
    DAMAGED_ROOF = 5


NUM_CLASSES = len(Cls)


# ---------- input ----------

@dataclass
class View:
    view_id: int        # 1-based, shown in the report as "view 1", "view 2"
    image_path: Path


@dataclass
class Case:
    case_id: str
    mode: str           # "photo" | "photos" | "video"
    views: list[View]


# ---------- metrics (epic 3) ----------

@dataclass
class FrameMetrics:
    view_id: int
    counts: list[int]                       # pixels per class, index = Cls
    facade_px: int                          # intact + damaged facade + broken windows
    roof_px: int                            # intact + damaged roof
    facade_share: float                     # facade_px / all pixels in the frame
    roof_share: float
    damaged_facade_ratio: float | None      # None when the surface is not visible at all
    broken_window_ratio: float | None
    damaged_roof_ratio: float | None
    facade_usable: bool
    roof_usable: bool
    excluded_reasons: list[str] = field(default_factory=list)


@dataclass
class CombinedRatios:
    """Ratios for the whole building: sum of damaged pixels / sum of surface pixels over usable frames."""
    damaged_facade: float | None
    broken_window: float | None
    damaged_roof: float | None
    facade_views: int                       # how many frames contributed to the facade ratios
    roof_views: int


# ---------- building parameters (epic 4, owned by a teammate) ----------

@dataclass
class BuildingParams:
    floors: int | None
    floor_height_m: float
    width_m: float | None
    depth_m: float | None
    roof_shape_coef: float
    auto_detected: set[str] = field(default_factory=set)   # names of fields filled automatically
    assumptions: list[str] = field(default_factory=list)   # e.g. "depth assumed equal to width"

    @property
    def height_m(self) -> float | None:
        return None if self.floors is None else self.floors * self.floor_height_m


@dataclass
class DamagedAreas:
    wall_area_m2: float
    roof_area_m2: float
    damaged_facade_m2: float | None
    broken_window_m2: float | None
    damaged_roof_m2: float | None


# ---------- decision layer and cost (epic 6) ----------

@dataclass
class WorkItem:
    work_type: str          # code from core.reference.WORK_TYPES, e.g. "facade_plaster_repair"
    damage_class: str       # which damaged surface it repairs, e.g. "damaged_facade"
    quantity: float | None  # m2, computed by code from DamagedAreas; None if the area is unknown
    unit: str = "m2"


@dataclass
class Decision:
    category: int           # 1..4, core.reference.CATEGORIES (task 6.3)
    category_name: str
    confidence: float       # 0..1
    works: list[WorkItem]
    escalation: str = "show"   # "show" | "inspect" | "not_classified" (task 6.6)


@dataclass
class CostLine:
    work: WorkItem
    item_name: str
    unit_price: float
    cost: float


@dataclass
class CostEstimate:
    lines: list[CostLine]
    total: float
    low: float
    high: float
    currency: str = "UAH"


# ---------- output ----------

@dataclass
class Report:
    case_id: str
    mode: str
    views_assessed: int
    frames: list[FrameMetrics]
    ratios: CombinedRatios
    building: BuildingParams | None = None
    areas: DamagedAreas | None = None
    decision: Decision | None = None
    cost: CostEstimate | None = None
    skipped_frames: dict[int, str] = field(default_factory=dict)   # view_id -> error
    masks: dict[int, np.ndarray] = field(default_factory=dict, repr=False)
