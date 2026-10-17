"""Cost calculation (epic 6.5): quantities x database prices, as a range.

Done by code, never by the model. Uses only the PriceSource interface, so it
contains no SQL and does not know whether prices come from the DB or a CSV.
"""
from __future__ import annotations

from datetime import date

from core import config
from core.interfaces import PriceSource
from core.types import CostEstimate, CostLine, Decision


def estimate_cost(decision: Decision, price_source: PriceSource, views_assessed: int,
                  as_of: date | None = None, max_candidates: int | None = None) -> CostEstimate:
    if as_of is None:
        as_of = date.today()
    if max_candidates is None:
        max_candidates = config.get("prices", "max_candidates")

    lines: list[CostLine] = []
    total = 0.0
    for work in decision.works:
        if work.quantity is None:                 # area unknown -> cannot cost it
            continue
        for item in price_source.get_items_by_work_type(work.work_type, max_candidates):
            try:
                unit_price = price_source.get_price_as_of(item["id"], as_of)
            except LookupError:
                continue                          # no price yet -> skip this material
            material_qty = work.quantity * item["quantity_per_unit"]
            cost = material_qty * unit_price
            total += cost
            lines.append(CostLine(work=work, item_name=item["name"],
                                  unit_price=unit_price, cost=cost))

    # Range widens with fewer assessed views (task 3.6 coefficients).
    half = (config.get("uncertainty", "scale_error")
            + config.get("uncertainty", "coverage_coef") / max(views_assessed, 1))
    return CostEstimate(lines=lines, total=total,
                        low=total * (1 - half), high=total * (1 + half))
