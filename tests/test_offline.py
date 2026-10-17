"""Without --gemini / the UI toggle no request may leave the machine: cached answers or stubs only."""
import numpy as np

from core.types import CombinedRatios
from models.offline import CachedOrStubBuilding, CachedOrStubDecision


def test_offline_falls_back_to_stubs_without_requests(tmp_path, monkeypatch):
    from core import config
    monkeypatch.setitem(config.load_config()["paths"], "cache", str(tmp_path))   # empty cache
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    b, d = CachedOrStubBuilding(), CachedOrStubDecision()
    mask = np.ones((100, 100), dtype=np.uint8)
    params = b.estimate([np.zeros((100, 100, 3), dtype=np.uint8)], [mask])
    assert b.last_source == "stub" and params.floors == 5
    decision = d.decide(CombinedRatios(0.2, 0.1, None, 1, 0), None, params)
    assert d.last_source == "stub" and decision.damage_category in ("I", "II", "III")
