"""The parts of the decision step done by code, not by the model: quantities and escalation."""
from core import config
from core.reference import WALL_WORKS, WORK_TYPES_BY_CODE
from core.types import BuildingParams, Cls, DamagedAreas, FacadeState, WorkItem


def damaged_area_of(cls: Cls, areas: DamagedAreas | None) -> float | None:
    if areas is None:
        return None
    return {
        Cls.DAMAGED_FACADE: areas.damaged_facade_m2,
        Cls.BROKEN_WINDOW: areas.broken_window_m2,
        Cls.DAMAGED_ROOF: areas.damaged_roof_m2,
    }[cls]


def wall_thickness(building: BuildingParams | None) -> float:
    """Outer wall thickness for the structure type ([geometry] wall_thickness_m)."""
    table = config.get("geometry", "wall_thickness_m")
    kind = (building.structure_type if building else None) or "unknown"
    return table.get(kind, table["unknown"])


def wall_works(facade: FacadeState, damaged_facade_m2: float | None, building: BuildingParams | None) -> list[WorkItem]:
    """The works on the walls, in the order they are done, from the model's assessment of the damaged facade:
      window openings (share w of the damaged area) go to the window works, the rest is wall;
      wall destroyed through (share d of the wall): debris removal and masonry, in m3 of wall (x thickness);
      all of the wall: finish (plaster, or the insulation system on an insulated facade) and painting;
      scaffolding over the wall area when the building has more than one floor."""
    area = None if damaged_facade_m2 is None else damaged_facade_m2 * (1 - facade.window_openings_share)
    t = wall_thickness(building)

    def item(code: str, quantity: float | None) -> WorkItem:
        wt = WORK_TYPES_BY_CODE[code]
        return WorkItem(work_type=code, damage_class=wt.damage_class.name.lower(), quantity=quantity, unit=wt.unit)

    destroyed_m3 = None if area is None else area * facade.destroyed_wall_share * t
    items = []
    if facade.destroyed_wall_share > 0:
        items += [item("facade_debris_removal", destroyed_m3), item("facade_masonry_repair", destroyed_m3)]
    items.append(item("facade_etics_repair" if facade.insulated else "facade_plaster_repair", area))
    items.append(item("facade_painting", area))
    if building is None or building.floors is None or building.floors > 1:
        items.append(item("facade_scaffolding", area))
    return items


def works_with_quantities(codes: list[str], areas: DamagedAreas | None, facade: FacadeState | None = None,
                          building: BuildingParams | None = None, facade_damaged: bool = False) -> list[WorkItem]:
    """Wall works from the facade assessment (wall_works), then the works the model chose for windows and roof.
    Window quantity = broken windows + the window openings inside the damaged facade."""
    items = []
    damaged_facade = areas.damaged_facade_m2 if areas else None
    if facade_damaged and facade is not None:
        items += wall_works(facade, damaged_facade, building)
    for code in dict.fromkeys(codes):          # keep order, drop duplicates
        if code in WALL_WORKS:                 # only the facade assessment adds wall works
            continue
        wt = WORK_TYPES_BY_CODE[code]
        area = damaged_area_of(wt.damage_class, areas)
        if area is not None and wt.damage_class == Cls.BROKEN_WINDOW and damaged_facade and facade:
            area += damaged_facade * facade.window_openings_share
        items.append(WorkItem(work_type=code, damage_class=wt.damage_class.name.lower(), quantity=area, unit=wt.unit))
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
