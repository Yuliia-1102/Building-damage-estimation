import numpy as np
import pytest

from core.geometry import damaged_areas, value_range
from core.metrics import combine, count_pixels, frame_metrics
from core.types import BuildingParams, Cls


def make_mask(spec: dict[Cls, int], size: int = 100) -> np.ndarray:
    """Flat mask with exactly the given number of pixels per class, rest background."""
    flat = np.full(size * size, Cls.BACKGROUND, dtype=np.uint8)
    pos = 0
    for cls, n in spec.items():
        flat[pos:pos + n] = cls
        pos += n
    return flat.reshape(size, size)


def test_count_pixels():
    mask = make_mask({Cls.FACADE: 300, Cls.ROOF: 50, Cls.BROKEN_WINDOW: 7})
    counts = count_pixels(mask)
    assert counts == [10000 - 357, 300, 50, 0, 7, 0]


def test_frame_ratios_and_denominators():
    mask = make_mask({Cls.FACADE: 1400, Cls.DAMAGED_FACADE: 400, Cls.BROKEN_WINDOW: 200,
                      Cls.ROOF: 600, Cls.DAMAGED_ROOF: 400})
    f = frame_metrics(1, mask, min_facade_share=0.05, min_roof_share=0.05)
    assert f.facade_px == 2000 and f.roof_px == 1000
    assert f.damaged_facade_ratio == pytest.approx(0.2)
    assert f.broken_window_ratio == pytest.approx(0.1)
    assert f.damaged_roof_ratio == pytest.approx(0.4)
    assert f.facade_usable and f.roof_usable


def test_zero_denominator():
    f = frame_metrics(1, make_mask({}), min_facade_share=0.05, min_roof_share=0.05)
    assert f.damaged_facade_ratio is None and f.damaged_roof_ratio is None
    assert not f.facade_usable and not f.roof_usable


def test_ground_level_frame_excluded_from_roof():
    mask = make_mask({Cls.FACADE: 5000, Cls.ROOF: 100, Cls.DAMAGED_ROOF: 100})
    f = frame_metrics(1, mask, min_facade_share=0.05, min_roof_share=0.05)
    assert f.facade_usable and not f.roof_usable
    assert f.excluded_reasons and f.excluded_reasons[0].startswith("roof")


def test_combine_is_division_of_sums():
    kw = dict(min_facade_share=0.05, min_roof_share=0.05)
    frames = [
        frame_metrics(1, make_mask({Cls.FACADE: 900, Cls.DAMAGED_FACADE: 100}), **kw),   # 10%
        frame_metrics(2, make_mask({Cls.FACADE: 2000, Cls.DAMAGED_FACADE: 1000}), **kw), # 33%
        frame_metrics(3, make_mask({Cls.FACADE: 10, Cls.DAMAGED_FACADE: 10}), **kw),     # excluded
    ]
    c = combine(frames)
    assert c.facade_views == 2
    assert c.damaged_facade == pytest.approx(1100 / 4000)
    assert c.damaged_roof is None and c.roof_views == 0


def test_damaged_areas():
    kw = dict(min_facade_share=0.05, min_roof_share=0.05)
    c = combine([frame_metrics(1, make_mask({Cls.FACADE: 800, Cls.DAMAGED_FACADE: 200,
                                             Cls.ROOF: 900, Cls.DAMAGED_ROOF: 100}), **kw)])
    b = BuildingParams(floors=5, floor_height_m=3.0, width_m=20.0, depth_m=10.0, roof_shape_coef=1.0)
    a = damaged_areas(c, b)
    assert a.wall_area_m2 == pytest.approx(2 * 30 * 15)
    assert a.roof_area_m2 == pytest.approx(200)
    assert a.damaged_facade_m2 == pytest.approx(0.2 * 900)
    assert a.damaged_roof_m2 == pytest.approx(0.1 * 200)


def test_fewer_views_wider_range():
    lo1, hi1 = value_range(100.0, views=1, scale_error=0.15, coverage_coef=0.3)
    lo5, hi5 = value_range(100.0, views=5, scale_error=0.15, coverage_coef=0.3)
    assert hi1 - lo1 > hi5 - lo5
    assert lo5 < 100 < hi5


def test_worst_view_and_damage_by_third():
    kw = dict(min_facade_share=0.05, min_roof_share=0.05)
    m1 = np.full((90, 10), Cls.FACADE, dtype=np.uint8)
    m1[60:90, :] = Cls.DAMAGED_FACADE                    # damage in the lower third only
    m2 = np.full((90, 10), Cls.FACADE, dtype=np.uint8)
    m2[0:9, :] = Cls.DAMAGED_FACADE                      # a little damage at the top
    c = combine([frame_metrics(1, m1, **kw), frame_metrics(2, m2, **kw)])
    assert c.worst_facade_view == 1 and c.worst_facade_damage == pytest.approx(1 / 3)
    assert c.damage_by_third == pytest.approx([300 / 390, 0, 90 / 390])


def test_worst_section_finds_one_destroyed_wing():
    from core.metrics import worst_section
    mask = np.full((90, 90), Cls.FACADE, dtype=np.uint8)
    mask[:, :30] = Cls.DAMAGED_FACADE          # left third destroyed, the rest intact
    assert worst_section(mask, 3) == pytest.approx(1.0)
    whole = (mask == Cls.DAMAGED_FACADE).mean()
    assert whole == pytest.approx(1 / 3)
    assert worst_section(np.zeros((10, 10), dtype=np.uint8), 3) is None
