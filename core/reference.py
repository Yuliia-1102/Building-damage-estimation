"""Reference tables the decision layer chooses from.

CATEGORIES: technical condition categories from ДСТУ-Н Б В.1.2-18:2016 (Настанова щодо обстеження
будівель і споруд для визначення та оцінки їх технічного стану). Task 6.3: confirm the standard is
still in force and that the wording below matches it.

WORK_TYPES: must match the `code` column of the work_type table in the materials database.
Every unit is m2, because the system measures damage as area only.
"""
from dataclasses import dataclass

from core.types import Cls

CATEGORIES = {
    1: ("normal", "No defects that reduce load-bearing capacity or serviceability; "
                  "at most cosmetic damage."),
    2: ("satisfactory", "Defects that do not affect load-bearing capacity; the building can be used, "
                        "repairs restore durability and appearance."),
    3: ("unfit for normal use", "Damage that reduces load-bearing capacity or makes normal use impossible "
                                "without repair; no immediate danger of collapse."),
    4: ("emergency", "Damage indicating danger of collapse; use must stop and people must be kept away."),
}


@dataclass(frozen=True)
class WorkType:
    code: str
    damage_class: Cls
    name: str
    unit: str = "m2"


WORK_TYPES = [
    WorkType("facade_plaster_repair", Cls.DAMAGED_FACADE, "Facade plaster repair"),
    WorkType("facade_masonry_repair", Cls.DAMAGED_FACADE, "Masonry wall repair"),
    WorkType("facade_painting", Cls.DAMAGED_FACADE, "Facade painting"),
    WorkType("window_glazing_replacement", Cls.BROKEN_WINDOW, "Glazing replacement"),
    WorkType("window_unit_replacement", Cls.BROKEN_WINDOW, "Window unit replacement"),
    WorkType("roof_covering_repair", Cls.DAMAGED_ROOF, "Roof covering repair"),
    WorkType("roof_covering_replacement", Cls.DAMAGED_ROOF, "Roof covering replacement"),
]

WORK_TYPES_BY_CODE = {w.code: w for w in WORK_TYPES}
