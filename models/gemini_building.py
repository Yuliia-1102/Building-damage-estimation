"""Building parameters from a photo with Gemini (tasks 4.1-4.4).

The model looks at the frame with the most facade and returns, as fixed fields: the floor count, the
structure type (ДСТУ 9273, 11.25), the roof type, and, for the fallback when floors cannot be read,
a door, car or person with its box in the image. Code then turns that into metres using the mask.
Every value is marked as detected automatically, so the user can correct it.
"""
import io
import logging
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from core import building as geom
from core import cache, config
from core.types import BuildingParams
from models.gemini_client import GeminiJSON

log = logging.getLogger(__name__)

STRUCTURE_TYPES = ("brick", "large_panel", "monolithic_frame", "precast_frame", "steel_frame", "wooden", "unknown")


class BuildingResponse(BaseModel):
    """Task 4.1: the parameter fields the model must return."""
    floors: int | None = Field(None, ge=1, le=60, description="Number of above-ground floors, null if unreadable")
    floors_confidence: float = Field(ge=0, le=1)
    structure_type: Literal[STRUCTURE_TYPES]
    roof_type: Literal["flat", "pitched", "unknown"]
    reference_object: Literal["door", "car", "person", "none"] = Field(
        description="An object of known size standing at the facade, for when floors cannot be read")
    reference_box: list[int] | None = Field(
        None, description="[ymin, xmin, ymax, xmax] of the reference object, normalised to 0-1000")


SYSTEM_INSTRUCTION = """\
You read basic parameters of a building from a photograph for a preliminary damage assessment.
Answer only with the JSON fields requested.
"""

PROMPT = """\
The photo shows a damaged building (the largest building in the frame).
- floors: count the above-ground floors from the rows of windows and balconies. Count a destroyed
  floor if its position is still visible. Null if you cannot count them.
- floors_confidence: how sure you are about the floor count.
- structure_type: brick (visible brick masonry or plastered brick walls), large_panel (precast concrete
  panels with visible joints), monolithic_frame (cast concrete frame with infill walls), precast_frame,
  steel_frame, wooden, or unknown.
- roof_type: flat or pitched.
- reference_object: if floors cannot be counted, pick one door, car or person standing at the facade,
  in the same plane as the wall, and give its box. Otherwise "none".
"""


def _jpeg(image: np.ndarray, max_side: int = 1024) -> bytes:
    im = Image.fromarray(image)
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class GeminiBuildingEstimator:
    def __init__(self, client=None, model: str | None = None, use_cache: bool = True):
        self.llm = GeminiJSON(client=client, model=model or config.get("decision", "building_model"),
                              use_cache=use_cache)

    def ask(self, image: np.ndarray) -> BuildingResponse:
        from google.genai import types
        data = _jpeg(image)
        contents = [types.Part.from_bytes(data=data, mime_type="image/jpeg"), PROMPT]
        return self.llm.ask(contents, BuildingResponse, SYSTEM_INSTRUCTION, "building",
                            [PROMPT, cache.text_key(data.hex())])

    def estimate(self, images: list[np.ndarray], masks: list[np.ndarray]) -> BuildingParams:
        """Asks about the frame with the most facade; if neither the floors nor a reference object can be
        read on it, asks about the next frames, up to [geometry] floor_frame_attempts in all."""
        attempts = config.get("geometry", "floor_frame_attempts")
        tried = []
        for i in geom.frames_for_floors(masks)[:attempts]:
            answer = self.ask(images[i])
            log.info("building answer for frame %d: %s", i, answer)
            tried.append(i)
            if answer.floors is not None or answer.reference_object != "none":
                break
        p = params_from_answer(answer, masks[i])
        p.source_frame = i
        if len(tried) > 1:
            p.assumptions.append(f"floors read on frame {i + 1}; not readable on frame(s) "
                                 f"{', '.join(str(t + 1) for t in tried[:-1])}")
        return p


def params_from_answer(answer: BuildingResponse, mask: np.ndarray) -> BuildingParams:
    """Code part of the estimate: height, scale, width, depth, roof coefficient, consequence class."""
    floor_h = config.get("geometry", "default_floor_height_m")
    roof_coef = config.get("geometry", "roof_shape_coef_pitched" if answer.roof_type == "pitched"
                           else "roof_shape_coef_flat")
    p = BuildingParams(
        floors=answer.floors,
        floor_height_m=floor_h,
        width_m=None,
        depth_m=None,
        roof_shape_coef=roof_coef,
        structure_type=answer.structure_type,
        roof_type=answer.roof_type,
        auto_detected={"floors", "structure_type", "roof_type", "width_m", "depth_m"},
    )
    if answer.roof_type == "unknown":
        p.assumptions.append("roof type unknown, flat roof assumed")

    if answer.floors is not None:
        p.height_source = "floors"
        if answer.floors_confidence < 0.5:
            p.assumptions.append(f"floor count uncertain (confidence {answer.floors_confidence:.2f})")
    elif answer.reference_object != "none" and answer.reference_box and len(answer.reference_box) == 4:
        ref_m = config.get("geometry", "reference_heights_m")[answer.reference_object]
        ymin, _, ymax, _ = answer.reference_box
        ref_px = (ymax - ymin) / 1000 * mask.shape[0]
        p.height_override_m = geom.height_from_reference(mask, ref_m, ref_px)
        p.height_source = f"reference object: {answer.reference_object} ({ref_m} m)"
        p.auto_detected.add("height_override_m")
        p.assumptions.append(f"floors not readable, height from a {answer.reference_object} of {ref_m} m")
    else:
        p.assumptions.append("floors not readable and no reference object: dimensions unknown, enter them")

    if p.height_m is not None:
        p.width_m, _ = geom.width_from_height(mask, p.height_m)
        p.depth_m = p.width_m
        p.assumptions.append("depth assumed equal to width (no corner view used)")
    p.occupants_estimate, p.consequence_class = geom.consequence_class(p.floors, p.width_m, p.depth_m)
    return p


def recompute(p: BuildingParams, mask: np.ndarray, changed: set[str]) -> BuildingParams:
    """After the user edits a field (task 4.5): fields they changed are kept and no longer marked automatic;
    width and depth are re-derived from the new height unless the user set them too."""
    p.auto_detected -= changed
    p.height_source = "user" if changed & {"floors", "floor_height_m", "height_override_m"} else p.height_source
    if p.height_m is not None and "width_m" not in changed:
        p.width_m, _ = geom.width_from_height(mask, p.height_m)
    if p.width_m is not None and "depth_m" not in changed:
        p.depth_m = p.width_m
    if "roof_type" in changed:
        p.roof_shape_coef = config.get("geometry", "roof_shape_coef_pitched" if p.roof_type == "pitched"
                                       else "roof_shape_coef_flat")
    p.occupants_estimate, p.consequence_class = geom.consequence_class(p.floors, p.width_m, p.depth_m)
    return p
