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
    # damaged facade + broken window pixels in the lower / middle / upper third of the building's height
    damage_by_third: list[int] = field(default_factory=lambda: [0, 0, 0])
    # damage share of the worst vertical section of the facade (one of N equal parts of its width)
    worst_section: float | None = None
    facade_aspect: float | None = None      # facade width / height in pixels (visible wall width = aspect x height)


@dataclass
class CombinedRatios:
    """Ratios for the whole building: sum of damaged pixels / sum of surface pixels over usable frames."""
    damaged_facade: float | None
    broken_window: float | None
    damaged_roof: float | None
    facade_views: int                       # how many frames contributed to the facade ratios
    roof_views: int
    # The worst single view: the building's category is set by its worst structure (ДСТУ 9273, 5.3),
    # and an average over views can hide one destroyed side.
    worst_facade_view: int | None = None
    worst_facade_damage: float | None = None    # damaged facade + broken windows, share of visible facade
    worst_roof_view: int | None = None
    worst_roof_damage: float | None = None
    # Share of facade damage in the lower / middle / upper third of the building (ДСТУ 9273, 11.26:
    # damage to the lower floors is more dangerous). None when there is no facade damage.
    damage_by_third: list[float] | None = None
    # The worst vertical section of the facade in any view: one destroyed section of a long building
    # is diluted in the whole-view share (ДСТУ 9273, 5.3: the worst part decides).
    worst_section_view: int | None = None
    worst_section_damage: float | None = None
    roof_partly_seen: bool = False    # roof ratios come from views where only a strip of roof is visible


# ---------- building parameters (epic 4) ----------

@dataclass
class BuildingParams:
    floors: int | None
    floor_height_m: float
    width_m: float | None
    depth_m: float | None
    roof_shape_coef: float
    structure_type: str | None = None       # core.reference.STRUCTURE_TYPES, ДСТУ 9273 clause 11.25
    roof_type: str | None = None            # "flat" | "pitched"
    height_override_m: float | None = None  # height from a reference object when floors cannot be read
    height_source: str | None = None        # "floors" | "reference object: door" | "user" ...
    occupants_estimate: int | None = None   # rough number of people, for the consequence class
    consequence_class: str | None = None    # "CC1" | "CC2" | "CC3", ДБН В.1.2-14:2018 table 1 (estimate)
    auto_detected: set[str] = field(default_factory=set)   # names of fields filled automatically
    assumptions: list[str] = field(default_factory=list)   # e.g. "depth assumed equal to width"
    source_frame: int | None = None    # index of the frame the floors were read on; its mask gives the scale

    @property
    def height_m(self) -> float | None:
        if self.floors is not None:
            return self.floors * self.floor_height_m
        return self.height_override_m


@dataclass
class DamagedAreas:
    wall_area_m2: float                 # all walls: perimeter x height
    roof_area_m2: float | None          # None when the roof was not assessed
    damaged_facade_m2: float | None     # share of damage x VISIBLE wall area
    broken_window_m2: float | None
    damaged_roof_m2: float | None
    visible_wall_area_m2: float | None = None   # walls seen in the views; damage is measured only there


# ---------- decision layer and cost (epic 6) ----------

@dataclass
class WorkItem:
    work_type: str          # code from core.reference.WORK_TYPES, e.g. "facade_plaster_repair"
    damage_class: str       # which damaged surface it repairs, e.g. "damaged_facade"
    quantity: float | None  # m2, computed by code from DamagedAreas; None if the area is unknown
    unit: str = "m2"


@dataclass
class Decision:
    damage_category: str        # "I" | "II" | "III", core.reference.DAMAGE_CATEGORIES - the main triage result
    condition_category: int     # 1..4, core.reference.CONDITION_CATEGORIES
    confidence: float           # 0..1
    works: list[WorkItem]
    # How far the categories can be trusted for ordering inspections (task 6.6):
    # "confirmed" | "preliminary" | "insufficient_data"
    escalation: str = "confirmed"
    roof_covering_category: int | None = None   # computed in code from table В.7.1, not by the model
    is_stub: bool = False       # a fixed placeholder (no model answer): never shown as a result

    @property
    def damage_name(self) -> str:
        from core.reference import DAMAGE_CATEGORIES
        return DAMAGE_CATEGORIES[self.damage_category][0]

    @property
    def condition_name(self) -> str:
        from core.reference import CONDITION_CATEGORIES
        return CONDITION_CATEGORIES[self.condition_category][0]


@dataclass
class CostLine:
    work_type: str          # which work this line belongs to
    item_name: str          # a material, or "labour"
    quantity: float         # in the item's unit, for the whole damaged area
    unit: str
    unit_price: float
    cost: float
    price_date: str | None = None   # as-of date of the price used, so the estimate is reproducible


@dataclass
class CostEstimate:
    lines: list[CostLine]
    total: float
    low: float
    high: float
    currency: str = "UAH"
    as_of: str | None = None
    skipped_works: list[str] = field(default_factory=list)   # works with unknown area or no price
    price_source: str = ""      # where the prices came from, shown in the report


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
    errors: list[str] = field(default_factory=list)                # steps that failed, shown in the report
    masks: dict[int, np.ndarray] = field(default_factory=dict, repr=False)
    excluded: dict[int, np.ndarray] = field(default_factory=dict, repr=False)   # other buildings in the frame
