import numpy as np
import pytest

from core import building as geom
from core.types import Cls
from models.gemini_building import BuildingResponse, params_from_answer, recompute


def facade_mask(h=100, w=200, top=50, left=100):
    """A 1000x1000 frame with an h x w facade rectangle."""
    m = np.zeros((1000, 1000), dtype=np.uint8)
    m[top:top + h, left:left + w] = Cls.FACADE
    return m


def test_extent_and_width_from_height():
    m = facade_mask()
    assert geom.facade_extent_px(m, percentile=95) == (100, 200)
    width, scale = geom.width_from_height(m, 15.0)
    assert scale == pytest.approx(0.15) and width == pytest.approx(30.0)


def test_height_from_reference_object():
    assert geom.height_from_reference(facade_mask(), ref_height_m=2.1, ref_height_px=20) == pytest.approx(10.5)


def test_consequence_class():
    assert geom.consequence_class(5, 30, 12) == (60, "CC2")
    assert geom.consequence_class(16, 60, 15) == (480, "CC3")
    assert geom.consequence_class(None, 30, 12) == (None, None)


def answer(**kw):
    base = dict(floors=5, floors_confidence=0.9, structure_type="large_panel", roof_type="flat",
                reference_object="none", reference_box=None)
    return BuildingResponse(**{**base, **kw})


def test_params_from_floor_count():
    p = params_from_answer(answer(), facade_mask())
    assert p.height_m == 15 and p.width_m == pytest.approx(30) and p.depth_m == pytest.approx(30)
    assert p.height_source == "floors" and "floors" in p.auto_detected
    assert any("depth assumed" in a for a in p.assumptions)


def test_reference_fallback_when_floors_unreadable():
    # a door 20% of the facade height -> 2.1 m / 20 px; facade 100 px -> 10.5 m
    p = params_from_answer(answer(floors=None, reference_object="door", reference_box=[130, 0, 150, 10]),
                           facade_mask())
    assert p.height_m == pytest.approx(10.5) and p.height_source.startswith("reference object: door")


def test_no_height_means_no_dimensions():
    p = params_from_answer(answer(floors=None), facade_mask())
    assert p.height_m is None and p.width_m is None


def test_user_edit_recomputes_width_and_drops_auto_flag():
    m = facade_mask()
    p = params_from_answer(answer(), m)
    p.floors = 6
    p = recompute(p, m, {"floors"})
    assert p.width_m == pytest.approx(36) and "floors" not in p.auto_detected and p.height_source == "user"


def test_next_frame_is_tried_when_floors_are_not_readable(monkeypatch):
    from models import gemini_building as gb
    est = gb.GeminiBuildingEstimator.__new__(gb.GeminiBuildingEstimator)
    answers = iter([gb.BuildingResponse(floors=None, floors_confidence=0.1, structure_type="brick",
                                        roof_type="flat", reference_object="none"),
                    gb.BuildingResponse(floors=5, floors_confidence=0.9, structure_type="brick",
                                        roof_type="flat", reference_object="none")])
    asked = []
    monkeypatch.setattr(est, "ask", lambda image: asked.append(image) or next(answers), raising=False)
    big, small = np.zeros((100, 100), np.uint8), np.zeros((100, 100), np.uint8)
    big[10:90, 10:90] = 1
    small[40:90, 40:60] = 1
    p = est.estimate([np.zeros((100, 100, 3), np.uint8)] * 2, [small, big])
    assert len(asked) == 2 and p.floors == 5 and p.source_frame == 0


def test_main_building_leaves_out_a_neighbour():
    m = np.zeros((100, 200), np.uint8)
    m[20:90, 60:150] = Cls.FACADE           # our building, central and large
    m[40:90, 5:30] = Cls.FACADE             # a smaller neighbour at the edge
    main = geom.main_building(m, grid=100, gap=0.03)
    assert main[50, 100] and not main[50, 15]


def test_main_building_keeps_a_building_split_by_a_narrow_gap():
    m = np.zeros((100, 200), np.uint8)
    m[20:90, 40:98] = Cls.FACADE
    m[20:90, 101:160] = Cls.DAMAGED_FACADE   # 3 px gap, e.g. a collapsed strip
    main = geom.main_building(m, grid=200, gap=0.03)
    assert main[50, 60] and main[50, 140]


def test_depth_from_views_takes_the_end_wall():
    long_side = np.zeros((100, 200), np.uint8)
    long_side[20:80, 20:180] = Cls.FACADE    # aspect 160/60
    end_wall = np.zeros((100, 200), np.uint8)
    end_wall[20:80, 80:120] = Cls.FACADE     # aspect 40/60
    d = geom.depth_from_views([long_side, end_wall, long_side], height_m=15, width_m=25)
    assert d == pytest.approx(10)
    assert geom.depth_from_views([long_side], height_m=15, width_m=40) is None


def test_damage_is_measured_on_the_walls_seen():
    from core.geometry import damaged_areas
    from core.metrics import combine, frame_metrics
    from core.types import BuildingParams
    m = np.zeros((100, 200), np.uint8)
    m[20:80, 50:110] = Cls.FACADE            # one side seen, 60 x 60 px: aspect 1
    m[20:50, 50:110] = Cls.DAMAGED_FACADE
    r = combine([frame_metrics(1, m)])
    b = BuildingParams(floors=5, floor_height_m=3.0, width_m=15.0, depth_m=15.0, roof_shape_coef=1.0)
    a = damaged_areas(r, b, [frame_metrics(1, m)])
    assert a.visible_wall_area_m2 == pytest.approx(15 * 15)     # one wall of four
    assert a.damaged_facade_m2 == pytest.approx(0.5 * 225)
    assert a.roof_area_m2 is None                                # roof not seen, not assessed
