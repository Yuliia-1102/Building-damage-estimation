"""The parts of the decision step done by code, not by the model: quantities and escalation."""
from core import config
from core.reference import WORK_TYPES_BY_CODE
from core.types import Cls, DamagedAreas, WorkItem


def damaged_area_of(cls: Cls, areas: DamagedAreas | None) -> float | None:
    if areas is None:
        return None
    return {
        Cls.DAMAGED_FACADE: areas.damaged_facade_m2,
        Cls.BROKEN_WINDOW: areas.broken_window_m2,
        Cls.DAMAGED_ROOF: areas.damaged_roof_m2,
    }[cls]


def works_with_quantities(codes: list[str], areas: DamagedAreas | None) -> list[WorkItem]:
    """The model only names the work types; the quantity of each is the damaged area of its surface."""
    items = []
    for code in dict.fromkeys(codes):          # keep order, drop duplicates
        wt = WORK_TYPES_BY_CODE[code]
        items.append(WorkItem(work_type=code, damage_class=wt.damage_class.name.lower(),
                              quantity=damaged_area_of(wt.damage_class, areas), unit=wt.unit))
    return items


def escalation_level(confidence: float, high: float | None = None, low: float | None = None) -> str:
    """High confidence: show the conclusion. Medium: show it, flagged for an engineer. Low: do not classify."""
    high = config.get("confidence", "high") if high is None else high
    low = config.get("confidence", "low") if low is None else low
    if confidence >= high:
        return "show"
    if confidence >= low:
        return "inspect"
    return "not_classified"
