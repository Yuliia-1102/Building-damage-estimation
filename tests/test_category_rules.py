"""Rules the code enforces whatever the model answers: masonry only for a local breach in category I, no restoration for III,
no roof area priced from a roof seen only as a strip, a typical depth when the end wall is not seen."""
from core.decision import apply_category_rules
from core.geometry import damaged_areas
from core.pipeline import evaluate, segment_case
from core.types import BuildingParams, CombinedRatios, Case, FacadeState, View
from models.gemini_building import assumed_depth
from tests.doubles import StubBuildingParams, StubDecisionLayer, StubSegmenter


def test_category_one_masonry_only_for_a_local_breach():
    facade = apply_category_rules("I", FacadeState(window_openings_share=0.2, destroyed_wall_share=0.4))
    assert facade.destroyed_wall_share == 0.1 and facade.window_openings_share == 0.2
    assert apply_category_rules("I", FacadeState(destroyed_wall_share=0.05)).destroyed_wall_share == 0.05
    assert apply_category_rules("II", FacadeState(destroyed_wall_share=0.4)).destroyed_wall_share == 0.4


def test_roof_seen_as_a_strip_gets_no_area():
    b = BuildingParams(floors=9, floor_height_m=3, width_m=60, depth_m=12, roof_shape_coef=1.0)
    ratios = CombinedRatios(damaged_facade=0.1, broken_window=0.0, damaged_roof=0.7, facade_views=1, roof_views=1,
                            roof_partly_seen=True)
    a = damaged_areas(ratios, b)
    assert a.roof_area_m2 is None and a.damaged_roof_m2 is None
    ratios.roof_partly_seen = False
    assert abs(damaged_areas(ratios, b).damaged_roof_m2 - 0.7 * 60 * 12) < 1e-6


def test_typical_depth_never_more_than_width():
    assert assumed_depth(99) == 12 and assumed_depth(8) == 8


class CategoryThree(StubDecisionLayer):
    def decide(self, *a, **k):
        d = super().decide(*a, **k)
        d.is_stub, d.damage_category, d.condition_category = False, "III", 4
        return d


def test_category_three_is_not_restored(tmp_path):
    import numpy as np
    from PIL import Image
    from models.price_source import default_price_source
    from core.report_pdf import summary_ua
    path = tmp_path / "a.png"
    Image.fromarray(np.zeros((120, 160, 3), dtype=np.uint8)).save(path)
    seg = segment_case(Case("c", "photo", [View(1, path)]), StubSegmenter())
    r = evaluate(seg, building_estimator=StubBuildingParams(), decision_layer=CategoryThree(),
                 price_source=default_price_source())
    assert r.decision.works == [] and r.cost is None
    assert "відновлення недоцільне" in summary_ua(r)
