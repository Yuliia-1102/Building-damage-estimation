"""The engine end to end on a real photo with the real segmentation model and a fake Gemini client:
no paid request is made here. Every assessment sends requests (there is no answer cache), and a failed
request fails the processing instead of producing a partial result."""
import json
from types import SimpleNamespace

import pytest

from core import config
from core.service import Engine, ProcessingError

PHOTO = config.ROOT.parent / "Dataset_CVAT" / "images" / "default" / "photo_2024-05-04_17-13-39.jpg"
pytestmark = pytest.mark.skipif(not config.path("weights").exists() or not PHOTO.exists(),
                                reason="needs the segmentation weights and a dataset photo")

BUILDING = json.dumps({"floors": 2, "floors_confidence": 0.9, "structure_type": "brick", "roof_type": "pitched",
                       "reference_object": "none", "reference_box": None})
DECISION = json.dumps({"damage_category": "I", "condition_category": 2, "confidence": 0.8,
                       "facade": {"window_openings_share": 0.2, "destroyed_wall_share": 0.05, "insulated": False},
                       "work_types": ["window_glazing_replacement"]})


class FakeGemini:
    """Answers the building request, then the decision request; fail=True fails every request."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, model, contents, config):
        schema = config.response_schema.__name__
        self.calls.append(schema)
        if self.fail:
            raise RuntimeError("no network in tests")
        return SimpleNamespace(text=BUILDING if schema == "BuildingResponse" else DECISION, usage_metadata=None)


def engine(monkeypatch, tmp_path, client):
    monkeypatch.setattr("models.gemini_client.make_client", lambda: client)
    return Engine(cache_root=tmp_path / "cache")


def test_assessment_asks_gemini_every_time(monkeypatch, tmp_path):
    client = FakeGemini()
    e = engine(monkeypatch, tmp_path, client)
    data = e.process([PHOTO], tmp_path / "a")
    assert data["summary"]["damage_category"] == "I" and data["summary"]["cost_low"] > 0
    assert data["sources"] == {"segmentation": "model", "building": "gemini", "decision": "gemini"}
    first = len(client.calls)
    e.process([PHOTO], tmp_path / "b")
    assert len(client.calls) == 2 * first          # the same photo again: new requests, nothing cached
    again = e.reevaluate(tmp_path / "a", {"floors": 3})
    assert client.calls[-1] == "DecisionResponse" and again["revision"] == 2


def test_failed_request_fails_the_processing(monkeypatch, tmp_path):
    client = FakeGemini(fail=True)
    with pytest.raises(ProcessingError) as err:
        engine(monkeypatch, tmp_path, client).process([PHOTO], tmp_path / "out")
    assert client.calls and "Gemini" not in err.value.user_message
    assert not (tmp_path / "out" / "result.json").exists()
