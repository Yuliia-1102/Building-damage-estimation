"""Test fixtures for the web system: an isolated data folder, a test engine, uploads made on the fly.

The test engine is core.service.Engine with test doubles in place of the segmentation model and Gemini, so
the real processing, saving, reevaluation and failure handling run without weights, network or cost.
The environment is set before any `web` import so the database and data folders point into a temp directory.
"""
import hashlib
import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="webtest_")
os.environ["DAMAGE_WEB_DATA"] = _TMP

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from core import service as core_service  # noqa: E402
from core.service import Engine, ProcessingError  # noqa: E402
from tests.doubles import StubBuildingParams, StubDecisionLayer, StubSegmenter  # noqa: E402


class Answer(StubDecisionLayer):
    """A model answer: category I with high confidence, or no assessment when low=True."""
    low = False

    def decide(self, *a, **k):
        d = super().decide(*a, **k)
        d.is_stub = False
        d.confidence, d.escalation = (0.2, "insufficient_data") if self.low else (0.8, "confirmed")
        return d


class TestEngine(Engine):
    """File names steer it: "fail" makes the model request fail, "lowconf" gives no assessment."""

    def __init__(self):
        from models.price_source import default_price_source
        self.segmenter, self.quick = StubSegmenter(), None
        self.building, self.decision = StubBuildingParams(), Answer()
        self.prices = default_price_source()

    def process(self, inputs, out_dir, case_id=None, progress=None):
        names = " ".join(p.name for p in inputs)
        if "fail" in names:
            raise ProcessingError("Не вдалося отримати відповідь сервісу оцінювання.")
        self.decision.low = "lowconf" in names
        return super().process(inputs, out_dir, case_id, progress)


core_service._engine = TestEngine()
UPLOADS = os.path.join(_TMP, "_test_files")


def make_file(name: str, content: str | None = None) -> str:
    """An image named `name`; its pixels depend on `content` (default: the name), so the same content under
    another name is a duplicate and different content is not."""
    os.makedirs(UPLOADS, exist_ok=True)
    seed = int(hashlib.sha256((content or name).encode()).hexdigest()[:8], 16)
    path = os.path.join(UPLOADS, name)
    Image.fromarray(np.random.default_rng(seed).integers(0, 255, (120, 160, 3), dtype=np.uint8)).save(path)
    return path


@pytest.fixture
def client():
    from web import config
    from web.db import Base, engine, init_db
    Base.metadata.drop_all(engine)
    for d in (config.UPLOADS_DIR, config.RESULTS_DIR):
        shutil.rmtree(d, ignore_errors=True)
    init_db()
    from web.server import app
    return TestClient(app)


@pytest.fixture
def create(client):
    def _create(names, title: str = "тест", project_id: str = "", content: str | None = None):
        names = [names] if isinstance(names, str) else names
        files = []
        for n in names:
            with open(make_file(n, content), "rb") as f:
                files.append(("files", (n, f.read(), "application/octet-stream")))
        r = client.post("/applications", data={"title": title, "comment": "", "project_id": project_id},
                        files=files, follow_redirects=False)
        assert r.status_code == 303, r.text
        return int(r.headers["location"].split("/applications/")[1].split("?")[0])
    return _create


@pytest.fixture
def pump():
    """Drain the worker queue synchronously, like the background worker would."""
    from core.service import get_engine
    from web import service
    from web.db import session_scope
    from web.worker import process_one

    def _pump(n: int = 30):
        eng = get_engine()
        for _ in range(n):
            with session_scope() as s:
                a = service.claim_next(s)
                aid = a.id if a else None
            if aid is None:
                break
            process_one(eng, aid)
    return _pump


@pytest.fixture
def db():
    from web.db import session_scope
    return session_scope
