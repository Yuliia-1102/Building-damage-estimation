"""Reference tables the decision layer chooses from (see the Confluence page "Condition and damage scales").

CONDITION_CATEGORIES: technical condition, ДСТУ 9273:2024 section 5. The building's category is set by
its worst main structure (responsibility categories А1, А, Б of ДБН В.1.2-14:2018), clause 5.3.

DAMAGE_CATEGORIES: Methodology of inspection, Ministry order No. 144 of 06.08.2022, Додаток 3. The
percentages are the damage of the whole building, not the share of damaged facade we measure.

WORK_TYPES: must match the `code` column of the work_type table in the materials database.
Every unit is m2, because the system measures damage as area only.
"""
from dataclasses import dataclass

from core.types import Cls

CONDITION_CATEGORIES = {
    1: ("normal", "No defects or damage that reduce load-bearing capacity or durability."),
    2: ("satisfactory", "Partial deviations, defects or damage that may reduce durability, but do not "
                        "limit the use of the building."),
    3: ("unfit for normal use", "Main structures do not meet load-bearing or protective requirements; "
                                "integrity can be kept until repair, strengthening or replacement; "
                                "restricted use."),
    4: ("emergency", "Integrity of main structures cannot be guaranteed; danger of collapse; people must "
                     "be kept out of the danger zone and use must stop."),
}

DAMAGE_CATEGORIES = {
    "I": ("minor damage", "Minor damage to load-bearing and enclosing structures without violating "
                          "mechanical resistance and stability.", "up to 40%",
          "routine repair (up to 20%) or routine and/or capital repair (21-40%)"),
    "II": ("significant damage", "Damage to main load-bearing and enclosing structures requiring partial "
                                 "dismantling and/or strengthening.", "41-80%",
           "capital repair, reconstruction"),
    "III": ("destroyed", "Unfit for intended use, economic value lost, danger of collapse.", "81-100%",
            "urgent demolition"),
}


def roof_covering_category(damaged_roof_share: float | None) -> int | None:
    """Condition of the roof covering by damaged area, ДСТУ 9273:2024 table В.7.1.

    The table gives: «3» mass local damage up to 40% of the area, «4» over 40%. The 5% line between
    «2» (point and isolated local damage) and «3» is the team's assumption; leaks are not visible.
    """
    if damaged_roof_share is None:
        return None
    if damaged_roof_share > 0.40:
        return 4
    if damaged_roof_share > 0.05:
        return 3
    if damaged_roof_share > 0:
        return 2
    return 1


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
