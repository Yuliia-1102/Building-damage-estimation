"""Where each building parameter came from, in words for the report: read by the model from a photo, measured
from the mask, computed, assumed or entered by the user. Shared by the UI and the PDF."""
from core import config
from core.reference import STRUCTURE_NAMES_UA
from core.types import BuildingParams

MODEL = "модель за фото"
ENTERED = "введено користувачем"


def _num(x, unit=""):
    return "—" if x is None else f"{x:,.1f}{unit}".replace(",", " ").replace(".0" + unit, unit)


def _auto(b: BuildingParams, field: str, how: str) -> str:
    return how if field in b.auto_detected else ENTERED


def height_source(b: BuildingParams) -> str:
    src = b.height_source or ""
    if src == "floors":
        return f"розраховано: {b.floors} поверхів × {_num(b.floor_height_m, ' м')}"
    if src.startswith("reference object"):
        return "за еталонним об'єктом на фото (двері, авто або людина)"
    if src == "user":
        return "з введених даних"
    return "—"


def depth_source(b: BuildingParams) -> str:
    if "depth_m" not in b.auto_detected:
        return ENTERED
    if any(a.startswith("depth measured") for a in b.assumptions):
        return "виміряно за найвужчим видом (торець будівлі)"
    return "прийнято рівною ширині (торця не видно)"


def consequence_note(b: BuildingParams) -> str:
    """The consequence class with how it was estimated, or a dash."""
    if not b.consequence_class:
        return "—"
    per_person = config.get("geometry", "floor_area_per_person_m2")
    area = (b.floors or 0) * (b.width_m or 0) * (b.depth_m or b.width_m or 0)
    return (f"{b.consequence_class}: ≈ {b.occupants_estimate} осіб = площа поверхів {_num(area, ' м²')} ÷ "
            f"{per_person:.0f} м² на особу (житлова норма). Груба оцінка для черговості; офіційно клас "
            f"визначає проєкт (ДСТУ 8855)")


def parameter_rows(b: BuildingParams) -> list[tuple[str, str, str]]:
    """(parameter, value, where it came from) for the building parameters table."""
    roof = {"flat": "плаский", "pitched": "скатний"}.get(b.roof_type or "", "невідомо")
    return [
        ("Кількість поверхів", str(b.floors) if b.floors else "—", _auto(b, "floors", MODEL)),
        ("Висота", _num(b.height_m, " м"), height_source(b)),
        ("Ширина фасаду", _num(b.width_m, " м"), _auto(b, "width_m", "виміряно з маски в масштабі висоти")),
        ("Глибина", _num(b.depth_m, " м"), depth_source(b)),
        ("Тип конструкції", STRUCTURE_NAMES_UA.get(b.structure_type or "unknown", "невідомо"),
         _auto(b, "structure_type", MODEL)),
        ("Тип даху", roof, _auto(b, "roof_type", MODEL)),
    ]
