import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from core import cache
from core.decision import escalation_level, works_with_quantities
from core.types import CombinedRatios, DamagedAreas
from models.gemini_decision import GeminiDecisionLayer, build_prompt
from models.stub import StubSegmenter


@pytest.fixture(autouse=True)
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "cache_dir", lambda: tmp_path / "cache")


class CountingSegmenter(StubSegmenter):
    calls = 0

    def predict(self, image):
        self.calls += 1
        return super().predict(image)


def test_second_run_comes_from_cache(tmp_path):
    img = tmp_path / "a.png"
    Image.fromarray(np.zeros((40, 60, 3), dtype=np.uint8)).save(img)
    inner = CountingSegmenter()
    seg = cache.CachedSegmenter(inner, "test")

    first = seg.predict_path(img)
    second = seg.predict_path(img)
    assert inner.calls == 1 and seg.hits == 1
    assert np.array_equal(first, second)

    cache.clear()
    seg.predict_path(img)
    assert inner.calls == 2


RATIOS = CombinedRatios(damaged_facade=0.3, broken_window=0.1, damaged_roof=None, facade_views=3, roof_views=0)
AREAS = DamagedAreas(wall_area_m2=1000, roof_area_m2=200, damaged_facade_m2=300,
                     broken_window_m2=100, damaged_roof_m2=None)


class FakeClient:
    """Stands in for genai.Client: returns the queued texts one per call."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        self.calls += 1
        return SimpleNamespace(text=self.answers.pop(0))


GOOD = json.dumps({"damage_category": "II", "condition_category": 3, "confidence": 0.8,
                   "work_types": ["facade_masonry_repair", "window_unit_replacement"]})


def test_decision_retries_on_invalid_answer_and_computes_quantities():
    client = FakeClient('{"damage_category": "IV", "condition_category": 7}', GOOD)
    d = GeminiDecisionLayer(client=client, model="fake").decide(RATIOS, AREAS, None)
    assert client.calls == 2
    assert d.damage_category == "II" and d.condition_category == 3 and d.escalation == "confirmed"
    assert [(w.work_type, w.quantity) for w in d.works] == [
        ("facade_masonry_repair", 300), ("window_unit_replacement", 100)]


def test_unknown_work_type_is_rejected():
    bad = json.dumps({"damage_category": "I", "condition_category": 2, "confidence": 0.5,
                      "work_types": ["paint_the_moon"]})
    with pytest.raises(ValueError):
        GeminiDecisionLayer(client=FakeClient(bad, bad, bad), model="fake").decide(RATIOS, AREAS, None)


def test_same_prompt_is_answered_from_cache():
    client = FakeClient(GOOD)
    layer = GeminiDecisionLayer(client=client, model="fake")
    layer.decide(RATIOS, AREAS, None)
    layer.decide(RATIOS, AREAS, None)
    assert client.calls == 1


def test_prompt_marks_unseen_surface():
    prompt = build_prompt(RATIOS, AREAS, None)
    assert "damaged roof:   not visible" in prompt
    assert "30.0%" in prompt


def test_quantity_unknown_without_areas():
    assert works_with_quantities(["facade_painting"], None)[0].quantity is None


def test_escalation_levels():
    assert escalation_level(0.9, high=0.75, low=0.45) == "confirmed"
    assert escalation_level(0.6, high=0.75, low=0.45) == "preliminary"
    assert escalation_level(0.2, high=0.75, low=0.45) == "insufficient_data"


def test_roof_covering_category_follows_table_v71():
    from core.reference import roof_covering_category
    assert roof_covering_category(None) is None
    assert roof_covering_category(0.0) == 1
    assert roof_covering_category(0.30) == 3
    assert roof_covering_category(0.41) == 4


def test_prompt_has_worst_view_and_vertical_split():
    r = CombinedRatios(damaged_facade=0.2, broken_window=0.05, damaged_roof=0.5, facade_views=3, roof_views=1,
                       worst_facade_view=2, worst_facade_damage=0.6, worst_roof_view=1, worst_roof_damage=0.5,
                       damage_by_third=[0.7, 0.2, 0.1])
    prompt = build_prompt(r, None, None)
    assert "worst single view of the facade: 60.0%" in prompt
    assert "lower third 70%" in prompt
    assert "table В.7.1): category 4" in prompt


def test_two_alternative_repairs_of_same_area_are_rejected():
    double = json.dumps({"damage_category": "II", "condition_category": 3, "confidence": 0.7,
                         "work_types": ["facade_plaster_repair", "facade_masonry_repair"]})
    client = FakeClient(double, GOOD)
    d = GeminiDecisionLayer(client=client, model="fake").decide(RATIOS, AREAS, None)
    assert client.calls == 2 and [w.work_type for w in d.works] == ["facade_masonry_repair", "window_unit_replacement"]


def test_roof_works_follow_the_roof_type():
    from core.decision import match_roof_type
    codes = ["roof_covering_replacement", "roof_structure_repair", "facade_painting"]
    assert match_roof_type(codes, "flat") == ["flat_roof_replacement", "facade_painting"]
    assert match_roof_type(["flat_roof_repair"], "pitched") == ["roof_covering_repair"]
    assert match_roof_type(codes, None) == codes
