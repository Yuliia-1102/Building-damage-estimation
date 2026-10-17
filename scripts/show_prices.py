"""Show what the price source returns for each work type (manual check, not a test).

    python scripts/show_prices.py                      # all work types
    python scripts/show_prices.py roof_covering_replacement   # one work type

Prints the materials, quantities and prices exactly as get_items_by_work_type and
get_price_as_of return them, plus the cost per 1 m2 of work.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import config  # noqa: E402
from core.reference import WORK_TYPES_BY_CODE  # noqa: E402
from pricedb import (  # noqa: E402
    MaterialsDbPriceSource, get_engine, session_factory, sqlite_url,
)

AS_OF = date.today()
LIMIT = config.get("prices", "max_candidates")


def show(src, code: str) -> None:
    wt = WORK_TYPES_BY_CODE.get(code)
    title = wt.name if wt else code
    print(f"\n=== {code}  ({title}) ===")
    items = src.get_items_by_work_type(code, LIMIT)
    if not items:
        print("  (no materials — unknown work code?)")
        return
    cost_per_m2 = 0.0
    print(f"  {'material':24} {'qty/m2':>8} {'unit':5} {'price':>9} {'line/m2':>10}")
    for it in items:
        found = src.get_price_as_of(it["id"], AS_OF)
        if found is None:
            print(f"  {it['name']:24} {it['quantity_per_unit']:>8} {it['unit']:5} {'no price':>9}")
            continue
        price, _ = found
        line = it["quantity_per_unit"] * price
        cost_per_m2 += line
        print(f"  {it['name']:24} {it['quantity_per_unit']:>8} {it['unit']:5} "
              f"{price:>9.2f} {line:>10.2f}")
    print(f"  {'':24} {'':8} {'':5} {'materials':>9} {cost_per_m2:>10.2f} UAH")
    labour = src.get_labour_price_as_of(code, AS_OF)
    if labour is not None:
        print(f"  {'':24} {'':8} {'':5} {'labour':>9} {labour[0]:>10.2f} UAH")
        cost_per_m2 += labour[0]
    print(f"  {'':24} {'':8} {'':5} {'TOTAL/m2':>9} {cost_per_m2:>10.2f} UAH")


def main() -> None:
    db_path = config.path("materials_db")
    if not db_path.exists():
        print(f"No database at {db_path}. Run: python scripts/init_db.py")
        return
    engine = get_engine(sqlite_url(db_path))
    with session_factory(engine)() as session:
        src = MaterialsDbPriceSource(session)
        codes = sys.argv[1:] or list(WORK_TYPES_BY_CODE)
        for code in codes:
            show(src, code)


if __name__ == "__main__":
    main()
