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
