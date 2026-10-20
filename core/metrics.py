"""Masks -> damage ratios (epic 3, tasks 3.1-3.4)."""
import numpy as np

from core import config
from core.building import facade_aspect
from core.types import NUM_CLASSES, Cls, CombinedRatios, FrameMetrics


def count_pixels(mask: np.ndarray) -> list[int]:
    """Pixels of each class; index = Cls value (task 3.1)."""
    return np.bincount(mask.ravel(), minlength=NUM_CLASSES)[:NUM_CLASSES].tolist()


def surface_pixels(counts: list[int]) -> tuple[int, int]:
    """Denominators (task 3.2): visible facade and visible roof."""
    facade = counts[Cls.FACADE] + counts[Cls.DAMAGED_FACADE] + counts[Cls.BROKEN_WINDOW]
    roof = counts[Cls.ROOF] + counts[Cls.DAMAGED_ROOF]
    return facade, roof


def _ratio(num: int, den: int) -> float | None:
    return num / den if den > 0 else None


BUILDING_CLASSES = [Cls.FACADE, Cls.ROOF, Cls.DAMAGED_FACADE, Cls.BROKEN_WINDOW, Cls.DAMAGED_ROOF]


def damage_by_third(mask: np.ndarray) -> list[int]:
    """Facade damage pixels in the lower, middle and upper third of the building's vertical extent."""
    rows = np.flatnonzero(np.isin(mask, BUILDING_CLASSES).any(axis=1))
    if rows.size == 0:
        return [0, 0, 0]
    top, bottom = rows[0], rows[-1] + 1
    damaged = np.isin(mask[top:bottom], [Cls.DAMAGED_FACADE, Cls.BROKEN_WINDOW]).sum(axis=1)
    upper, middle, lower = (int(part.sum()) for part in np.array_split(damaged, 3))
    return [lower, middle, upper]


def worst_section(mask: np.ndarray, sections: int | None = None) -> float | None:
    """Damage share (damaged facade + broken windows) of the worst of N equal vertical sections of the facade.

    The sections split the horizontal extent of the facade; a section with almost no facade in it (under 2%
    of the facade) is ignored, so a thin edge does not produce a 100% ratio from a few pixels."""
    sections = sections or config.get("metrics", "facade_sections")
    facade = np.isin(mask, [Cls.FACADE, Cls.DAMAGED_FACADE, Cls.BROKEN_WINDOW])
    damaged = np.isin(mask, [Cls.DAMAGED_FACADE, Cls.BROKEN_WINDOW])
    cols = np.flatnonzero(facade.sum(axis=0) > 0.05 * mask.shape[0])
    if cols.size == 0:
        return None
    edges = np.linspace(cols[0], cols[-1] + 1, sections + 1).astype(int)
    total = facade.sum()
    shares = [damaged[:, a:b].sum() / facade[:, a:b].sum()
              for a, b in zip(edges[:-1], edges[1:]) if facade[:, a:b].sum() > 0.02 * total]
    return float(max(shares)) if shares else None


def frame_metrics(view_id: int, mask: np.ndarray,
                  min_facade_share: float | None = None,
                  min_roof_share: float | None = None) -> FrameMetrics:
    """Ratios for one frame plus whether it is usable for facade and for roof (task 3.3)."""
    if min_facade_share is None:
        min_facade_share = config.get("suitability", "min_facade_share")
    if min_roof_share is None:
        min_roof_share = config.get("suitability", "min_roof_share")

    counts = count_pixels(mask)
    facade_px, roof_px = surface_pixels(counts)
    total = mask.size
    facade_share = facade_px / total
    roof_share = roof_px / total

    reasons = []
    facade_usable = facade_share >= min_facade_share
    if not facade_usable:
        reasons.append(f"facade: {facade_share:.1%} of frame < {min_facade_share:.1%}")
    roof_usable = roof_share >= min_roof_share
    if not roof_usable:
        reasons.append(f"roof: {roof_share:.1%} of frame < {min_roof_share:.1%}")

    return FrameMetrics(
        view_id=view_id,
        counts=counts,
        facade_px=facade_px,
        roof_px=roof_px,
        facade_share=facade_share,
        roof_share=roof_share,
        damaged_facade_ratio=_ratio(counts[Cls.DAMAGED_FACADE], facade_px),
        broken_window_ratio=_ratio(counts[Cls.BROKEN_WINDOW], facade_px),
        damaged_roof_ratio=_ratio(counts[Cls.DAMAGED_ROOF], roof_px),
        facade_usable=facade_usable,
        roof_usable=roof_usable,
        excluded_reasons=reasons,
        damage_by_third=damage_by_third(mask),
        worst_section=worst_section(mask),
        facade_aspect=facade_aspect(mask),
    )


def combine(frames: list[FrameMetrics]) -> CombinedRatios:
    """Whole-building ratios as a division of sums over usable frames (task 3.4).

    Equivalent to averaging per-frame ratios weighted by visible surface pixels, so the same
    damage seen in two frames adds to both numerator and denominator and is not counted twice.
    """
    facade = [f for f in frames if f.facade_usable]
    roof = [f for f in frames if f.roof_usable]
    partly = False
    if not roof:            # no view shows much roof: use the strips of roof that are visible
        roof = [f for f in frames if f.roof_share >= config.get("suitability", "min_roof_share_fallback")]
        partly = bool(roof)

    facade_den = sum(f.facade_px for f in facade)
    roof_den = sum(f.roof_px for f in roof)

    def facade_damage(f: FrameMetrics) -> float:
        return (f.counts[Cls.DAMAGED_FACADE] + f.counts[Cls.BROKEN_WINDOW]) / f.facade_px

    worst_facade = max(facade, key=facade_damage, default=None)
    worst_roof = max(roof, key=lambda f: f.damaged_roof_ratio, default=None)

    sectioned = [f for f in facade if f.worst_section is not None]
    worst_sec = max(sectioned, key=lambda f: f.worst_section, default=None)

    thirds = [sum(f.damage_by_third[i] for f in facade) for i in range(3)]
    total = sum(thirds)

    return CombinedRatios(
        damaged_facade=_ratio(sum(f.counts[Cls.DAMAGED_FACADE] for f in facade), facade_den),
        broken_window=_ratio(sum(f.counts[Cls.BROKEN_WINDOW] for f in facade), facade_den),
        damaged_roof=_ratio(sum(f.counts[Cls.DAMAGED_ROOF] for f in roof), roof_den),
        facade_views=len(facade),
        roof_views=len(roof),
        worst_facade_view=worst_facade.view_id if worst_facade else None,
        worst_facade_damage=facade_damage(worst_facade) if worst_facade else None,
        worst_roof_view=worst_roof.view_id if worst_roof else None,
        worst_roof_damage=worst_roof.damaged_roof_ratio if worst_roof else None,
        damage_by_third=[t / total for t in thirds] if total else None,
        worst_section_view=worst_sec.view_id if worst_sec else None,
        worst_section_damage=worst_sec.worst_section if worst_sec else None,
        roof_partly_seen=partly,
    )
