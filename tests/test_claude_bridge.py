"""The Claude bridge: a request is exported instead of sent, an answer file is validated and cached."""
import json

import numpy as np
import pytest

from core import cache, config
from core.types import Cls, CombinedRatios, DamagedAreas


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setitem(config.load_config()["paths"], "output", str(tmp_path / "out"))


def test_export_answer_import_then_cached():
    from models import claude_bridge
    from models.gemini_decision import GeminiDecisionLayer
    ratios = CombinedRatios(0.3, 0.1, None, 1, 0, worst_section_view=1, worst_facade_view=1)
    areas = DamagedAreas(1000, None, 300, 100, None, 1000)
    image = np.full((60, 80, 3), 100, np.uint8)
    mask = np.full((60, 80), Cls.FACADE, np.uint8)
    mask[10:30, 10:40] = Cls.DAMAGED_FACADE
    layer = GeminiDecisionLayer(model="claude-sonnet-5-5")
    with pytest.raises(claude_bridge.AnswerPending):
        layer.decide(ratios, areas, None, views={1: (image, mask)})
    [folder] = claude_bridge.pending()
    request = json.loads((folder / "request.json").read_text())
    assert request["schema_name"] == "DecisionResponse" and request["images"] == ["image1.jpg"]
    assert (folder / "image1.jpg").exists() and "Damage category" in request["prompt"]

    facade = '"facade": {"window_openings_share": 0.1, "destroyed_wall_share": 0.3, "insulated": false}'
    (folder / "answer.json").write_text('{"damage_category": "II", "condition_category": 3, "confidence": 0.7, '
                                        '"work_types": ["facade_masonry_repair"]}')
    assert claude_bridge.import_answer(folder).startswith("invalid")       # no facade, a wall work chosen
    (folder / "answer.json").write_text('{"damage_category": "II", "condition_category": 3, "confidence": 0.7, '
                                        + facade + ', "work_types": []}')
    assert claude_bridge.import_answer(folder) == "ok"
    assert claude_bridge.pending() == []
    d = GeminiDecisionLayer(model="claude-sonnet-5-5").decide(ratios, areas, None, views={1: (image, mask)})
    assert d.damage_category == "II" and "facade_masonry_repair" in [w.work_type for w in d.works]
