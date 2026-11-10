"""Test fixtures for the web system: an isolated data folder, the simulator engine, and helpers.

The environment is set before any `web` import so the database and data folders point into a temp directory,
never the real data/. The engine is the simulator with no delay, so tests do not need the model weights.
"""
import os
import shutil
import tempfile

# Must be set before importing web.config / web.db (they read these at import time).
_TMP = tempfile.mkdtemp(prefix="webtest_")
os.environ["DAMAGE_WEB_DATA"] = _TMP
os.environ["DAMAGE_ENGINE"] = "simulator"
os.environ["DAMAGE_SIM_DELAY"] = "0"
os.environ.setdefault("DAMAGE_SIM_FAIL_RATE", "0")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from core import config as core_config  # noqa: E402

PACK = core_config.ROOT / "devpack"
pytestmark = pytest.mark.skipif(not (PACK / "index.json").exists(),
                                reason="devpack not installed (unzip devpack.zip into the repo root)")


def _case_file(case: str) -> str:
    folder = PACK / "inputs" / case
    files = sorted(p for p in folder.iterdir() if p.is_file())
    return str(files[0])


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
    def _create(case_or_path: str, title: str = "тест", project_id: str = ""):
        path = case_or_path if os.path.isfile(case_or_path) else _case_file(case_or_path)
        with open(path, "rb") as f:
            r = client.post("/applications",
                            data={"title": title, "comment": "", "project_id": project_id},
                            files=[("files", (os.path.basename(path), f.read(), "application/octet-stream"))],
                            follow_redirects=False)
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


def pack_path(*parts: str) -> str:
    return str(PACK.joinpath(*parts))
