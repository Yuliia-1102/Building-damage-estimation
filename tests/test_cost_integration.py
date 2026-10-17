"""End-to-end: assess() with the materials DB produces a cost estimate (epic 5 + 6.5)."""
import numpy as np
import pytest
from PIL import Image

from core.pipeline import assess
from core.types import Case, View
from models.stub import StubBuildingParams, StubDecisionLayer, StubSegmenter
from pricedb import create_db, load_seed, session_factory, sqlite_url, MaterialsDbPriceSource


@pytest.fixture
def price_source(tmp_path):
    engine = create_db(sqlite_url(tmp_path / "materials.db"))
    session = session_factory(engine)()
    load_seed(session)
    yield MaterialsDbPriceSource(session)
    session.close()


@pytest.fixture
def case(tmp_path):
    img_path = tmp_path / "view1.png"
    Image.fromarray(np.zeros((200, 300, 3), dtype=np.uint8)).save(img_path)
    return Case(case_id="t1", mode="photo", views=[View(view_id=1, image_path=img_path)])


def test_assess_produces_cost(case, price_source):
    report = assess(case, StubSegmenter(),
                    building_estimator=StubBuildingParams(),
                    decision_layer=StubDecisionLayer(),
                    price_source=price_source)

    assert report.cost is not None
    assert report.cost.total > 0
    assert report.cost.low < report.cost.total < report.cost.high
    assert report.cost.lines  # at least one priced material line


def test_no_price_source_means_no_cost(case):
    report = assess(case, StubSegmenter(),
                    building_estimator=StubBuildingParams(),
                    decision_layer=StubDecisionLayer())
    assert report.cost is None
