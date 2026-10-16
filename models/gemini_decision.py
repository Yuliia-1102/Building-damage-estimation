"""Decision layer on the Gemini API (tasks 6.1, 6.2, 6.4).

Numbers in, structured answer out: the model gets damage ratios and areas and returns a condition
category, a confidence and a list of work type codes, all as fixed fields with no free text.
It never computes quantities or prices; core/decision.py does that.
"""
import json
import logging
import os
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from core import cache, config
from core.decision import escalation_level, works_with_quantities
from core.reference import CATEGORIES, WORK_TYPES
from core.types import BuildingParams, CombinedRatios, DamagedAreas, Decision

log = logging.getLogger(__name__)

WorkTypeCode = Literal[tuple(w.code for w in WORK_TYPES)]


class DecisionResponse(BaseModel):
    """The fixed schema the model must fill (task 6.1). Anything else is rejected."""
    category: int = Field(ge=1, le=4, description="Technical condition category, 1-4")
    confidence: float = Field(ge=0.0, le=1.0, description="How sure the category is, 0-1")
    work_types: list[WorkTypeCode] = Field(description="Work type codes needed to restore the building")


SYSTEM_INSTRUCTION = """\
You classify the technical condition of a damaged building for preliminary triage.
You receive measurements extracted from photographs by a segmentation model. You do not see the photos.
Answer only with the JSON fields requested. Do not compute costs or quantities.
"""


def _pct(x: float | None) -> str:
    return "not visible" if x is None else f"{x:.1%}"


def _m2(x: float | None) -> str:
    return "unknown" if x is None else f"{x:.0f} m2"


def build_prompt(ratios: CombinedRatios, areas: DamagedAreas | None, building: BuildingParams | None) -> str:
    """Task 6.4: the rubric, the measurements and the allowed work types in one request."""
    rubric = "\n".join(f"  {k} - {name}: {desc}" for k, (name, desc) in CATEGORIES.items())
    works = "\n".join(f"  {w.code}  (repairs {w.damage_class.name.lower()}): {w.name}" for w in WORK_TYPES)

    lines = [
        "Condition categories (ДСТУ-Н Б В.1.2-18:2016):",
        rubric,
        "",
        "Measurements (share of the visible surface that is damaged):",
        f"  damaged facade: {_pct(ratios.damaged_facade)}  (from {ratios.facade_views} views)",
        f"  broken windows: {_pct(ratios.broken_window)}  (from {ratios.facade_views} views)",
        f"  damaged roof:   {_pct(ratios.damaged_roof)}  (from {ratios.roof_views} views)",
    ]
    if building is not None:
        lines.append(f"Building: {building.floors or 'unknown'} floors")
    if areas is not None:
        lines += [
            f"Areas: walls {_m2(areas.wall_area_m2)}, roof {_m2(areas.roof_area_m2)}; "
            f"damaged facade {_m2(areas.damaged_facade_m2)}, broken windows {_m2(areas.broken_window_m2)}, "
            f"damaged roof {_m2(areas.damaged_roof_m2)}",
        ]
    lines += [
        "",
        "Allowed work types:",
        works,
        "",
        "Rules:",
        "- Choose work types only for surfaces that show damage. A surface marked 'not visible' "
        "was not assessed: do not add works for it.",
        "- For each damaged surface choose the work types matching how severe the damage is.",
        "- confidence: low when few views were assessed or the measurements are borderline between "
        "two categories; high only when the category is clear.",
        "- Facade damage seen in photos cannot prove the state of load-bearing structures; "
        "lower confidence for categories 3 and 4 accordingly.",
    ]
    return "\n".join(lines)


class GeminiDecisionLayer:
    def __init__(self, client=None, model: str | None = None, retries: int = 2, use_cache: bool = True):
        if client is None:
            from dotenv import load_dotenv
            from google import genai
            load_dotenv()
            if not os.environ.get("GEMINI_API_KEY"):
                raise RuntimeError("GEMINI_API_KEY is not set, see .env.example")
            client = genai.Client()
        self.client = client
        self.model = model or config.get("decision", "model")
        self.retries = retries
        self.use_cache = use_cache

    def _call(self, prompt: str) -> str:
        from google.genai import types
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=DecisionResponse,
                temperature=0.0,
                seed=config.get("decision", "seed"),
            ),
        )
        return response.text

    def ask(self, prompt: str) -> DecisionResponse:
        """One validated answer, retried on a malformed one (task 6.1.3), cached by prompt (6.2.3)."""
        key = cache.text_key(self.model + "\n" + prompt)
        if self.use_cache and (hit := cache.get_json("decisions", key)) is not None:
            return DecisionResponse.model_validate(hit)

        last_error = None
        for attempt in range(1, self.retries + 2):
            raw = self._call(prompt)
            try:
                answer = DecisionResponse.model_validate_json(raw)
                break
            except ValidationError as e:
                last_error = e
                log.warning("decision attempt %d: response does not match the schema: %s", attempt, raw)
        else:
            raise ValueError(f"no valid decision after {self.retries + 1} attempts") from last_error

        if self.use_cache:
            cache.put_json("decisions", key, json.loads(answer.model_dump_json()))
        return answer

    def decide(self, ratios: CombinedRatios, areas: DamagedAreas | None,
               building: BuildingParams | None) -> Decision:
        answer = self.ask(build_prompt(ratios, areas, building))
        return Decision(
            category=answer.category,
            category_name=CATEGORIES[answer.category][0],
            confidence=answer.confidence,
            works=works_with_quantities(answer.work_types, areas),
            escalation=escalation_level(answer.confidence),
        )
