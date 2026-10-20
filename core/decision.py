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


def works_with_quantities(codes: list[str], areas: DamagedAreas | None, shares: dict[str, float] | None = None,
                          windows_in_destroyed: float = 0.0) -> list[WorkItem]:
    """The model names the works and, where several alternatives repair one surface, how its damaged area is
    split between them; code computes the quantities:
      - a work of an alternatives group: damaged area of its surface x its share (1 if it is the only one);
      - debris removal: the masonry share of the damaged facade (holed or destroyed walls), all of it if no
        masonry work was chosen; scaffolding and painting: the whole damaged facade;
      - windows: broken windows plus the window openings inside destroyed walls (damaged facade x
        windows_in_destroyed), which the segmentation counts as facade damage."""
    shares = shares or {}
    codes = list(dict.fromkeys(codes))         # keep order, drop duplicates
    masonry = shares.get("facade_masonry_repair", 1.0) if "facade_masonry_repair" in codes else None
    items = []
    for code in codes:
        wt = WORK_TYPES_BY_CODE[code]
        area = damaged_area_of(wt.damage_class, areas)
        if area is not None:
            if wt.damage_class == Cls.BROKEN_WINDOW and areas.damaged_facade_m2:
                area += areas.damaged_facade_m2 * windows_in_destroyed
            if code == "facade_debris_removal" and masonry is not None:
                area *= masonry
            elif wt.group:
                area *= shares.get(code, 1.0)
        items.append(WorkItem(work_type=code, damage_class=wt.damage_class.name.lower(),
                              quantity=area, unit=wt.unit))
    return items


def escalation_level(confidence: float, high: float | None = None, low: float | None = None) -> str:
    """How far the categories can be trusted when ordering buildings for inspection.

    Every building is inspected on site eventually; this only says whether its place in the queue is reliable.
    confirmed: use the category as is. preliminary: do not move the building to the end of the queue
    because of a mild category. insufficient_data: no category; add photos from other sides.
    """
    high = config.get("confidence", "high") if high is None else high
    low = config.get("confidence", "low") if low is None else low
    if confidence >= high:
        return "confirmed"
    if confidence >= low:
        return "preliminary"
    return "insufficient_data"


def match_roof_type(codes: list[str], roof_type: str | None) -> list[str]:
    """Roof works exist for pitched and for flat roofs. When the roof type is known, a work for the other kind
    is swapped for its counterpart (or dropped if it has none), so the materials and prices fit the roof."""
    if roof_type not in ("pitched", "flat"):
        return codes
    counterpart = {"roof_covering_repair": "flat_roof_repair", "roof_covering_replacement": "flat_roof_replacement"}
    counterpart.update({v: k for k, v in counterpart.items()})
    out = []
    for code in codes:
        wt = WORK_TYPES_BY_CODE[code]
        if wt.roof_type in (None, roof_type):
            out.append(code)
        elif code in counterpart:
            out.append(counterpart[code])
    return list(dict.fromkeys(out))
