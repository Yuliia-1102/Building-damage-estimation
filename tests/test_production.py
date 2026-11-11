"""Production mode: Gemini only. Even for a photo whose answer is in the development cache, a request is sent;
a failed request fails the processing (no stub answers, no partial result). No paid request is made here:
the Gemini client is replaced by a fake that records the call and fails."""
import pytest

from core import config
from core.service import Engine, ProcessingError

SCHOOL = config.ROOT.parent / "Dataset_CVAT" / "images" / "default" / "photo_2024-05-04_17-13-39.jpg"
pytestmark = pytest.mark.skipif(not config.path("weights").exists() or not SCHOOL.exists(),
                                reason="needs the segmentation weights and the dataset photo")


class FailingClient:
    def __init__(self):
        self.calls = []
        outer = self

        class models:
            @staticmethod
            def generate_content(**kw):
                outer.calls.append(kw["model"])
                raise RuntimeError("no network in tests")
        self.models = models


@pytest.fixture
def engine(tmp_path, monkeypatch):
    client = FailingClient()
    monkeypatch.setattr("models.gemini_client.make_client", lambda: client)
    monkeypatch.delenv("DAMAGE_LLM", raising=False)
    e = Engine(llm="production", cache_root=tmp_path / "cache")
    return e, client


def test_production_asks_gemini_even_when_the_dev_cache_has_the_answer(engine, tmp_path):
    e, client = engine
    assert e.name == "production"
    assert not e.building.llm.use_cache and not e.decision.llm.use_cache
    with pytest.raises(ProcessingError) as err:
        e.process([SCHOOL], tmp_path / "out")
    assert client.calls, "a request must be sent, the cache must not answer"
    assert all(m.startswith("gemini") for m in client.calls)
    assert "Gemini" not in err.value.user_message
    assert not (tmp_path / "out" / "result.json").exists()
    assert (tmp_path / "cache" / "masks").exists()          # its own mask cache, not the development one


def test_production_needs_its_own_cache_folder(monkeypatch):
    monkeypatch.delenv("DAMAGE_CACHE_DIR", raising=False)
    with pytest.raises(RuntimeError, match="DAMAGE_CACHE_DIR"):
        Engine(llm="production")


def test_production_refuses_the_claude_bridge(monkeypatch, tmp_path):
    monkeypatch.setenv("DAMAGE_LLM", "claude-sonnet-5-5")
    with pytest.raises(RuntimeError, match="Gemini only"):
        Engine(llm="production", cache_root=tmp_path)
