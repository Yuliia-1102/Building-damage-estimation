"""Ratios -> square metres, and the uncertainty range (epic 3, tasks 3.5-3.6).

Building dimensions are an input here; they come from the building parameters estimator (epic 4).
"""
from core import config
from core.types import BuildingParams, CombinedRatios, DamagedAreas


def wall_area(width_m: float, depth_m: float, height_m: float) -> float:
    return 2 * (width_m + depth_m) * height_m


def roof_area(width_m: float, depth_m: float, shape_coef: float) -> float:
    return width_m * depth_m * shape_coef


def visible_wall_area(frames, height_m: float, all_walls: float) -> float:
    """Wall area seen in the views: the facade pixels of each usable view times its metres per pixel squared
    (height in metres / building height in pixels). Not the bounding rectangle, which in a corner view also
    counts the sky and the yard between two wings. Summed over the views and capped at all walls, since views
    of the same side overlap. Perspective still makes the far parts of a facade count a little less."""
    seen = sum(f.facade_px * (height_m / f.facade_height_px) ** 2
               for f in frames if f.facade_usable and f.facade_height_px)
    return min(seen, all_walls) if seen else all_walls


def damaged_areas(ratios: CombinedRatios, building: BuildingParams, frames=None) -> DamagedAreas:
    """Each damage ratio times the area of the surface it was measured on: the walls seen in the views,
    not all walls (one photo shows one or two sides; damage elsewhere is unknown, not assumed). The roof
    area is given only when the roof was assessed. Unknown ratio stays None, not 0."""
    width = building.width_m
    depth = building.depth_m if building.depth_m is not None else width
    height = building.height_m
    if width is None or height is None:
        raise ValueError("building width and height are required to convert ratios to m2")

    walls = wall_area(width, depth, height)
    visible = visible_wall_area(frames, height, walls) if frames else walls
    roof = roof_area(width, depth, building.roof_shape_coef) if ratios.damaged_roof is not None else None

    def times(ratio: float | None, area: float | None) -> float | None:
        return None if ratio is None or area is None else ratio * area

    return DamagedAreas(
        wall_area_m2=walls,
        roof_area_m2=roof,
        damaged_facade_m2=times(ratios.damaged_facade, visible),
        broken_window_m2=times(ratios.broken_window, visible),
        damaged_roof_m2=times(ratios.damaged_roof, roof),
        visible_wall_area_m2=visible,
    )


def relative_half_width(views: int, scale_error: float | None = None,
                        coverage_coef: float | None = None) -> float:
    """Scale error plus a coverage term that shrinks as more views are assessed."""
    if scale_error is None:
        scale_error = config.get("uncertainty", "scale_error")
    if coverage_coef is None:
        coverage_coef = config.get("uncertainty", "coverage_coef")
    return scale_error + coverage_coef / max(views, 1)


def value_range(value: float, views: int, **kwargs) -> tuple[float, float]:
    """(low, high) around a point estimate (task 3.6)."""
    hw = relative_half_width(views, **kwargs)
    return max(0.0, value * (1 - hw)), value * (1 + hw)
