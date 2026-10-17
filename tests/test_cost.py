from datetime import date

import pytest

from core.cost import estimate_cost
from core.types import WorkItem
from models.csv_prices import CsvPriceSource


@pytest.fixture
def prices():
    return CsvPriceSource()


def test_price_history_takes_latest_before_date(prices):
    assert prices.get_price_as_of(1, date(2026, 6, 1)) == (7.5, "2026-01-01")
    assert prices.get_price_as_of(1, date(2026, 10, 1)) == (8.0, "2026-09-01")
    assert prices.get_price_as_of(1, date(2025, 1, 1)) is None


def test_cost_matches_manual_calculation(prices):
    works = [WorkItem("facade_plaster_repair", "damaged_facade", 10.0)]
    est = estimate_cost(works, prices, views=4, as_of=date(2026, 10, 1))
    # 10 m2 x (18 kg x 8.0 + 0.2 l x 80 + labour 350) = 10 x 510 = 5100
    assert est.total == pytest.approx(5100)
    assert est.low < est.total < est.high
    assert {l.item_name for l in est.lines} == {"Cement-sand plaster mix", "Facade primer", "labour"}


def test_unknown_area_is_skipped_not_zero(prices):
    est = estimate_cost([WorkItem("facade_painting", "damaged_facade", None)], prices, views=1)
    assert est.total == 0 and est.skipped_works
