"""The processing entry point for the web system: the saved result folder and loading it back."""
import json

import numpy as np
import pytest
from PIL import Image

from core.pipeline import evaluate, segment_case
from core.service import InputError, describe_inputs, input_mode, load_result, save_result
from core.types import Case, View
from tests.doubles import StubBuildingParams, StubDecisionLayer, StubSegmenter


class RealDecision(StubDecisionLayer):
    """The stub's answer marked as a real one, so the summary shows a category and a cost."""

    def decide(self, *a, **k):
        d = super().decide(*a, **k)
        d.is_stub = False
        d.confidence, d.escalation = 0.8, "confirmed"
        return d


@pytest.fixture
def photo(tmp_path):
    rng = np.random.default_rng(0)
    path = tmp_path / "in" / "house.jpg"
    path.parent.mkdir()
    Image.fromarray(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8)).save(path)
    return path


@pytest.fixture
def result(tmp_path, photo):
    case = Case("house", "photo", [View(1, photo)])
    seg = segment_case(case, StubSegmenter())
    from models.price_source import default_price_source
    report = evaluate(seg, building_estimator=StubBuildingParams(), decision_layer=RealDecision(),
                      price_source=default_price_source())
    out = tmp_path / "result"
    data = save_result(seg, report, out, describe_inputs([photo]), {"decision": "test"}, {})
    return out, data, report


def test_input_mode(tmp_path):
    assert input_mode([tmp_path / "a.jpg"]) == "photo"
    assert input_mode([tmp_path / "a.jpg", tmp_path / "b.png"]) == "photos"
    assert input_mode([tmp_path / "a.MP4"]) == "video"
    for bad in ([], [tmp_path / "a.txt"], [tmp_path / "a.mp4", tmp_path / "b.jpg"]):
        with pytest.raises(InputError):
            input_mode(bad)


def test_saved_folder_has_everything_the_web_page_needs(result):
    out, data, _ = result
    on_disk = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert on_disk["format_version"] == 1
    s = on_disk["summary"]
    assert s["has_assessment"] and s["damage_category"] == "I" and s["cost_low"] < s["cost_high"]
    assert (out / on_disk["pdf"]).read_bytes()[:4] == b"%PDF"
    for v in on_disk["views"]:
        for key in ("image", "overlay", "mask"):
            assert (out / v[key]).exists()
    assert len(on_disk["inputs"][0]["sha256"]) == 64


def test_load_result_gives_back_the_same_report(result):
    out, _, report = result
    seg, loaded, _ = load_result(out)
    assert loaded.decision.damage_category == report.decision.damage_category
    assert loaded.cost.total == pytest.approx(report.cost.total)
    assert loaded.building.floors == report.building.floors
    assert np.array_equal(seg.masks[1], report.masks[1])
