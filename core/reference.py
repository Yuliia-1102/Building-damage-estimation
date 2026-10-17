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
    # Works in the same group are alternatives for the same area (by severity): at most one is chosen,
    # otherwise the same square metres would be paid for twice. None = an additional work added on top.
    group: str | None = None
    roof_type: str | None = None      # "pitched" or "flat": the work only applies to that kind of roof


WORK_TYPES = [
    # damaged facade: one repair by severity, plus additional works
    WorkType("facade_plaster_repair", Cls.DAMAGED_FACADE, "Facade plaster repair (surface damage)",
             group="facade_repair"),
    WorkType("facade_etics_repair", Cls.DAMAGED_FACADE, "Insulated facade restoration (mineral wool, mesh, "
             "decorative plaster), for facades with external insulation", group="facade_repair"),
    WorkType("facade_masonry_repair", Cls.DAMAGED_FACADE, "Masonry wall rebuilding (holes, destroyed walls)",
             group="facade_repair"),
    WorkType("facade_painting", Cls.DAMAGED_FACADE, "Facade painting (finishing after plaster or masonry repair)"),
    WorkType("facade_debris_removal", Cls.DAMAGED_FACADE, "Dismantling of destroyed structures and debris removal "
             "(holes, collapsed or burnt parts)"),
    WorkType("facade_scaffolding", Cls.DAMAGED_FACADE, "Facade scaffolding (any facade work above the ground floor)"),
    # broken windows: one of three
    WorkType("window_glazing_replacement", Cls.BROKEN_WINDOW, "Glazing replacement (frames intact)", group="window"),
    WorkType("window_unit_replacement", Cls.BROKEN_WINDOW, "Window unit replacement (frames destroyed)",
             group="window"),
    WorkType("window_temporary_closure", Cls.BROKEN_WINDOW, "Temporary closure of openings with OSB boards and film "
             "(building to be dismantled or awaiting major repair)", group="window"),
    # damaged roof: one covering work matching the roof type, plus the roof structure for pitched roofs
    WorkType("roof_covering_repair", Cls.DAMAGED_ROOF, "Pitched roof covering repair (metal tile, local)",
             group="roof", roof_type="pitched"),
    WorkType("roof_covering_replacement", Cls.DAMAGED_ROOF, "Pitched roof covering replacement (metal tile, "
             "membrane, battens)", group="roof", roof_type="pitched"),
    WorkType("flat_roof_repair", Cls.DAMAGED_ROOF, "Flat roof repair (one layer of torch-on roofing)",
             group="roof", roof_type="flat"),
    WorkType("flat_roof_replacement", Cls.DAMAGED_ROOF, "Flat roof replacement (old covering removed, two layers "
             "of torch-on roofing)", group="roof", roof_type="flat"),
    WorkType("roof_structure_repair", Cls.DAMAGED_ROOF, "Rafter structure repair (burnt or collapsed pitched roof)",
             roof_type="pitched"),
]

WORK_TYPES_BY_CODE = {w.code: w for w in WORK_TYPES}


# Ukrainian labels for the interface and the PDF report.
CONDITION_NAMES_UA = {1: "нормальний", 2: "задовільний", 3: "непридатний до нормальної експлуатації",
                      4: "аварійний"}
DAMAGE_NAMES_UA = {"I": "незначні пошкодження", "II": "значні пошкодження", "III": "зруйнований об'єкт"}
DAMAGE_RECOMMENDATION_UA = {"I": "поточний та/або капітальний ремонт",
                            "II": "капітальний ремонт, реконструкція",
                            "III": "невідкладний демонтаж"}
WORK_NAMES_UA = {
    "facade_plaster_repair": "Ремонт штукатурки фасаду",
    "facade_etics_repair": "Відновлення утепленого фасаду",
    "facade_masonry_repair": "Відновлення кладки стін",
    "facade_painting": "Фарбування фасаду",
    "facade_debris_removal": "Розбирання зруйнованих конструкцій і вивезення сміття",
    "facade_scaffolding": "Риштування фасадне",
    "window_glazing_replacement": "Заміна скління",
    "window_unit_replacement": "Заміна віконних блоків",
    "window_temporary_closure": "Тимчасове закриття віконних прорізів (OSB)",
    "roof_covering_repair": "Ремонт скатної покрівлі",
    "roof_covering_replacement": "Заміна скатної покрівлі",
    "flat_roof_repair": "Ремонт плаского даху",
    "flat_roof_replacement": "Заміна покрівлі плаского даху",
    "roof_structure_repair": "Відновлення кроквяної системи",
}
STRUCTURE_NAMES_UA = {"brick": "цегляна", "large_panel": "великопанельна", "monolithic_frame": "монолітний каркас",
                      "precast_frame": "збірний залізобетонний каркас", "steel_frame": "металевий каркас",
                      "wooden": "дерев'яна", "unknown": "невідомо"}
ESCALATION_UA = {
    "confirmed": "Висока впевненість: категорію можна використовувати для черговості обстеження.",
    "preliminary": "Середня впевненість: категорія попередня. Не відсувайте будівлю в кінець черги через "
                   "легку категорію.",
    "insufficient_data": "Недостатньо даних: категорію не визначено. Додайте фото з інших боків або "
                         "вважайте пріоритет невідомим.",
}
DISCLAIMER_UA = (
    "Це попередня візуальна оцінка для визначення черговості обстежень, а не технічне обстеження. "
    "За зображеннями неможливо оцінити несучі конструкції всередині будівлі та приховані дефекти; "
    "обстеження лише за фото чи відео не допускається (Методика № 144). Кожна пошкоджена будівля "
    "потребує обстеження на місці."
)
