"""Decision layer on the Gemini API (tasks 6.1, 6.2, 6.4).

Numbers in, structured answer out: the model gets damage ratios, areas and building parameters and
returns a damage category, a technical condition category, a confidence and a list of work type codes,
all as fixed fields with no free text. It never computes quantities or prices; core/decision.py does that.
The scales are described on the Confluence page "Condition and damage scales".
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from core.decision import escalation_level, match_roof_type, works_with_quantities
from core.reference import (CONDITION_CATEGORIES, DAMAGE_CATEGORIES, WORK_TYPES, WORK_TYPES_BY_CODE,
                            roof_covering_category)
from core import cache, config
from core.imageio import building_box, overlay_for_model
from core.types import BuildingParams, CombinedRatios, DamagedAreas, Decision
from models.gemini_client import GeminiJSON

WorkTypeCode = Literal[tuple(w.code for w in WORK_TYPES)]


class DecisionResponse(BaseModel):
    """The fixed schema the model must fill (task 6.1). Anything else is rejected."""
    damage_category: Literal["I", "II", "III"] = Field(description="Damage category, Methodology No. 144")
    condition_category: int = Field(ge=1, le=4, description="Technical condition category, ДСТУ 9273:2024")
    confidence: float = Field(ge=0.0, le=1.0, description="How sure the categories are, 0-1")
    work_types: list[WorkTypeCode] = Field(description="Work type codes needed to restore the building")

    @field_validator("work_types")
    @classmethod
    def one_repair_per_surface(cls, codes):
        """Two alternative repairs of the same area would count the same square metres twice."""
        groups = [WORK_TYPES_BY_CODE[c].group for c in set(codes) if WORK_TYPES_BY_CODE[c].group]
        dup = {g for g in groups if groups.count(g) > 1}
        if dup:
            raise ValueError(f"more than one alternative work chosen for: {', '.join(sorted(dup))}")
        return codes


SYSTEM_INSTRUCTION = """\
You make a preliminary visual assessment of a damaged building, used only to order buildings for on-site
inspection. You receive measurements extracted from photographs by a segmentation model and, when available,
a few of those photographs with the segmentation drawn over them. Answer only with the JSON fields requested.
Do not compute costs or quantities.
"""

IMAGES_NOTE = """\
Images: {n} views of the building with the segmentation drawn over them, cropped to the building (views {ids}).
Colours: green = intact facade, purple = damaged facade, blue = broken windows, orange = intact roof,
red = damaged roof; uncoloured = not building. The fill is light so the photo stays visible under it.
The measured shares above are the main evidence. Use the images to judge what the damage is: holes through
walls, collapsed or burnt-out parts, missing floors, versus surface damage to plaster or cladding. The
segmentation can be wrong; trust what the photo shows."""


def _pct(x: float | None) -> str:
    return "not visible" if x is None else f"{x:.1%}"


def _m2(x: float | None) -> str:
    return "unknown" if x is None else f"{x:.0f} m2"


def build_prompt(ratios: CombinedRatios, areas: DamagedAreas | None, building: BuildingParams | None) -> str:
    """Task 6.4: both scales, the measurements, the allowed work types and the rules from the standards."""
    damage_scale = "\n".join(f"  {k} - {name}: {desc} Indicative damage of the whole building {pct}."
                             for k, (name, desc, pct, _) in DAMAGE_CATEGORIES.items())
    condition_scale = "\n".join(f"  {k} - {name}: {desc}" for k, (name, desc) in CONDITION_CATEGORIES.items())
    works = "\n".join(f"  {w.code}  (repairs {w.damage_class.name.lower()}"
                      f"{', alternatives group ' + w.group if w.group else ', additional work, can be added'}"
                      f"{', ' + w.roof_type + ' roofs only' if w.roof_type else ''}): {w.name}"
                      for w in WORK_TYPES)
    roof_cat = roof_covering_category(ratios.damaged_roof)

    lines = [
        "Damage category (Methodology of inspection, order No. 144, Додаток 3):",
        damage_scale,
        "",
        "Technical condition category (ДСТУ 9273:2024, section 5):",
        condition_scale,
        "",
        "Measurements (share of the VISIBLE surface that is damaged, over all usable views):",
        f"  damaged facade: {_pct(ratios.damaged_facade)}  (from {ratios.facade_views} views)",
        f"  broken windows: {_pct(ratios.broken_window)}  (from {ratios.facade_views} views)",
        f"  damaged roof:   {_pct(ratios.damaged_roof)}  (from {ratios.roof_views} views"
        f"{', only a strip of roof visible in them' if ratios.roof_partly_seen else ''})",
    ]
    if ratios.worst_facade_damage is not None:
        lines.append(f"  worst single view of the facade: {_pct(ratios.worst_facade_damage)} damaged "
                     f"(facade damage + broken windows)")
    if ratios.worst_section_damage is not None:
        lines.append(f"  worst vertical section of the facade (a third of its width) in a single view: "
                     f"{_pct(ratios.worst_section_damage)} damaged")
    if ratios.worst_roof_damage is not None:
        lines.append(f"  worst single view of the roof: {_pct(ratios.worst_roof_damage)} damaged")
    if ratios.damage_by_third is not None:
        low, mid, up = ratios.damage_by_third
        lines.append(f"  where the facade damage is: lower third {low:.0%}, middle third {mid:.0%}, "
                     f"upper third {up:.0%} of the building height")
    if roof_cat is not None:
        lines.append(f"  roof covering condition by damaged area (ДСТУ 9273, table В.7.1): category {roof_cat}")

    if building is not None:
        lines += ["", "Building:",
                  f"  floors: {building.floors or 'unknown'}",
                  f"  structure type: {building.structure_type or 'unknown'}",
                  f"  roof type: {building.roof_type or 'unknown'}"]
    if areas is not None:
        lines.append(f"  areas: walls {_m2(areas.wall_area_m2)}, roof {_m2(areas.roof_area_m2)}; "
                     f"damaged facade {_m2(areas.damaged_facade_m2)}, broken windows "
                     f"{_m2(areas.broken_window_m2)}, damaged roof {_m2(areas.damaged_roof_m2)}")

    lines += [
        "",
        "Allowed work types:",
        works,
        "",
        "Rules:",
        "- The building's category is set by its worst part, not by the average (ДСТУ 9273, 5.3): "
        "weigh the worst single view, not only the combined share.",
        "- A worst vertical section far above the whole-view share means one section of the building is "
        "destroyed while the rest is intact; a section destroyed through its height can make the whole building "
        "category II-III and condition 4.",
        "- Damage concentrated in the lower floors is more dangerous for the whole building than the same "
        "damage in the upper floors (ДСТУ 9273, 11.26).",
        "- The same damage means more in a panel or brick building than in a monolithic frame "
        "(ДСТУ 9273, 11.25).",
        "- The damage category percentages refer to the whole building, including structures that are not "
        "visible; the measured shares above are only the visible surface. Do not map them one to one.",
        "- The two answers must be consistent: I goes with condition 1-2, II with 3 or 4, III with 4. Give II with 4 "
        "when a part of the building is destroyed through its full height or its load-bearing walls are holed "
        "(a destroyed section, a collapsed corner), even if the rest is intact.",
        "- Choose work types only for surfaces that show damage. A surface marked 'not visible' was not "
        "assessed: do not add works for it.",
        "- Works in the same alternatives group repair the same area in different ways: choose at most ONE per "
        "group, the one matching the severity (e.g. masonry repair for destroyed walls, plaster repair for "
        "surface damage). Additional works can be added on top.",
        "- Roof works marked 'pitched roofs only' or 'flat roofs only' must match the roof type of the building.",
        "- Facade scaffolding is needed for facade works on buildings above one floor. Debris removal is needed "
        "when walls are holed, collapsed or burnt through.",
        "- For a building in damage category III do not restore windows; close the openings temporarily.",
        "- confidence: low when few views were assessed, a surface is not visible, or the measurements are "
        "borderline between two categories; high only when the category is clear. Load-bearing structures "
        "cannot be seen in photos, so be cautious with categories II-III and 3-4.",
    ]
    return "\n".join(lines)


def pick_views(ratios: CombinedRatios, views: dict, limit: int) -> list[int]:
    """Which views to show: the worst facade section, the worst facade view, the worst roof view, then the
    views with the most building, up to `limit`."""
    order = [ratios.worst_section_view, ratios.worst_facade_view, ratios.worst_roof_view]
    order += sorted(views, key=lambda v: -(views[v][1] > 0).mean())
    return [v for v in dict.fromkeys(order) if v in views][:limit]


def view_jpeg(image, mask, max_side: int = 1024) -> bytes:
    """The view as the model sees it: cropped to the building, segmentation drawn over it, longer side 1024 px."""
    from models.gemini_building import _jpeg
    top, bottom, left, right = building_box(mask)
    return _jpeg(overlay_for_model(image[top:bottom, left:right], mask[top:bottom, left:right]), max_side)


class GeminiDecisionLayer:
    def __init__(self, client=None, model: str | None = None, retries: int = 2, use_cache: bool = True):
        self.llm = GeminiJSON(client=client, model=model, retries=retries, use_cache=use_cache)
        self.last_images: list[bytes] = []       # what was shown to the model, saved with test runs

    def ask(self, prompt: str, images: list[bytes] = ()) -> DecisionResponse:
        parts = [prompt]
        if images:
            from google.genai import types
            parts += [types.Part.from_bytes(data=d, mime_type="image/jpeg") for d in images]
        key = [prompt, *(cache.text_key(d.hex()) for d in images)]
        return self.llm.ask(parts, DecisionResponse, SYSTEM_INSTRUCTION, "decisions", key)

    def decide(self, ratios: CombinedRatios, areas: DamagedAreas | None,
               building: BuildingParams | None, views: dict | None = None) -> Decision:
        """views: view_id -> (image, mask). Up to [decision] max_images of them are shown to the model."""
        prompt = build_prompt(ratios, areas, building)
        ids = pick_views(ratios, views, config.get("decision", "max_images")) if views else []
        images = [view_jpeg(*views[v]) for v in ids]
        if ids:
            prompt += "\n\n" + IMAGES_NOTE.format(n=len(ids), ids=", ".join(map(str, ids)))
        self.last_images = images
        answer = self.ask(prompt, images)
        return Decision(
            damage_category=answer.damage_category,
            condition_category=answer.condition_category,
            confidence=answer.confidence,
            works=works_with_quantities(match_roof_type(answer.work_types, building and building.roof_type), areas),
            escalation=escalation_level(answer.confidence),
            roof_covering_category=roof_covering_category(ratios.damaged_roof),
        )
