"""Cost calculation (task 6.5). Plain arithmetic, never the language model.

cost of a work = damaged area x (sum over its materials of quantity per m2 x material price + labour per m2)
The total is widened into a range by the same uncertainty as the areas (task 3.6).
"""
import logging
from datetime import date

from core import config, geometry
from core.interfaces import PriceSource
from core.types import CostEstimate, CostLine, WorkItem

log = logging.getLogger(__name__)


def estimate_cost(works: list[WorkItem], prices: PriceSource, views: int,
                  as_of: date | None = None) -> CostEstimate:
    as_of = as_of or date.today()
    limit = config.get("prices", "max_candidates")
    lines, skipped = [], []

    for work in works:
        if work.quantity is None:
            skipped.append(f"{work.work_type}: damaged area unknown")
            continue
        work_lines = []
        for item in prices.get_items_by_work_type(work.work_type, limit):
            price = prices.get_price_as_of(item["id"], as_of)
            if price is None:
                log.warning("no price for %s as of %s", item["name"], as_of)
                continue
            value, valid_from = price
            qty = work.quantity * item["quantity_per_unit"]
            work_lines.append(CostLine(work.work_type, item["name"], qty, item["unit"], value, qty * value,
                                       valid_from))
        labour = getattr(prices, "get_labour_price_as_of", lambda *_: None)(work.work_type, as_of)
        if labour is not None:
            value, valid_from = labour
            work_lines.append(CostLine(work.work_type, "labour", work.quantity, work.unit, value,
                                       work.quantity * value, valid_from))
        if not work_lines:
            skipped.append(f"{work.work_type}: no prices in the catalogue")
        lines += work_lines

    total = sum(line.cost for line in lines)
    low, high = geometry.value_range(total, views)
    return CostEstimate(lines=lines, total=total, low=low, high=high, as_of=as_of.isoformat(),
                        skipped_works=skipped)
