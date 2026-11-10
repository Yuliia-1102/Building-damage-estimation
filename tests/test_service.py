"""The processing entry point for the web system: saved result folder, loading it back, the simulator."""
import json

import numpy as np
import pytest
from PIL import Image

from core.pipeline import evaluate, segment_case
from core.service import InputError, describe_inputs, input_mode, load_result, save_result
from core.simulator import SimulatedEngine, SimulatedFailure
from core.types import Case, View
from models.stub import StubBuildingParams, StubDecisionLayer, StubSegmenter


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
    assert on_disk["format_version"] == 1 and not on_disk["simulated"]
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


@pytest.fixture
def pack(tmp_path, result, photo):
    out, data, _ = result
    pack = tmp_path / "pack"
    (pack / "results").mkdir(parents=True)
    import shutil
    shutil.copytree(out, pack / "results" / "house")
    (pack / "index.json").write_text(json.dumps({"cases": [
        {"case_id": "house", "inputs": data["inputs"], "result": "results/house"}]}), encoding="utf-8")
    return SimulatedEngine(pack, delay=(0, 0), fail_rate=0)


def test_simulator_returns_the_recorded_result_for_a_pack_file(pack, photo, tmp_path):
    seen = []
    data = pack.process([photo], tmp_path / "app1", case_id="APP-1", progress=lambda s, t: seen.append(s))
    assert data["simulated"] and data["simulation"]["matched"]
    assert data["case_id"] == "APP-1" and data["summary"]["damage_category"] == "I"
    assert seen[-1] == 1.0
    assert json.loads((tmp_path / "app1" / "result.json").read_text())["case_id"] == "APP-1"


def test_simulator_unknown_file_failure_and_no_assessment(pack, tmp_path):
    other = tmp_path / "other.jpg"
    Image.fromarray(np.zeros((50, 50, 3), dtype=np.uint8)).save(other)
    assert not pack.process([other], tmp_path / "a")["simulation"]["matched"]
    fail = tmp_path / "fail_test.jpg"
    fail.write_bytes(other.read_bytes())
    with pytest.raises(SimulatedFailure):
        pack.process([fail], tmp_path / "b")
    low = tmp_path / "lowconf_test.jpg"
    low.write_bytes(other.read_bytes())
    s = pack.process([low], tmp_path / "c")["summary"]
    assert not s["has_assessment"] and s["cost_low"] is None and s["escalation"] == "insufficient_data"


def test_simulator_reevaluate_changes_the_cost(pack, photo, tmp_path):
    before = pack.process([photo], tmp_path / "app")
    after = pack.reevaluate(tmp_path / "app", {"floors": before["summary"]["floors"] * 2})
    assert after["revision"] == 2 and after["simulated"]
    assert after["summary"]["cost_total"] > before["summary"]["cost_total"]
    assert after["sources"]["building"] == "operator"
    with pytest.raises(InputError):
        pack.reevaluate(tmp_path / "app", {"price": 1})
