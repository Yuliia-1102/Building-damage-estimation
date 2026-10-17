"""Tests for the materials database and its PriceSource (epic 5)."""
from datetime import date

import pytest
from sqlalchemy import func, select

from core.reference import WORK_TYPES
from pricedb import (
    DamageClass, Material, Price, WorkType, create_db, load_seed,
    session_factory, sqlite_url, MaterialsDbPriceSource, CsvPriceSource, export_csv,
)
from pricedb import seed_data


@pytest.fixture
def session(tmp_path):
    engine = create_db(sqlite_url(tmp_path / "materials.db"))
    with session_factory(engine)() as s:
        load_seed(s)
        yield s


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


# --- schema + seed -----------------------------------------------------------
def test_seed_fills_every_table(session):
    assert _count(session, DamageClass) == 3
    assert _count(session, Material) == len(seed_data.MATERIALS)
    assert _count(session, Price) == len(seed_data.PRICES)
    assert _count(session, WorkType) == len(seed_data.WORKS)


def test_work_codes_match_reference(session):
    db_codes = {w.code for w in session.scalars(select(WorkType))}
    ref_codes = {w.code for w in WORK_TYPES}
    assert db_codes == ref_codes


# --- the PriceSource contract ------------------------------------------------
def test_get_items_by_work_type_returns_dicts(session):
    src = MaterialsDbPriceSource(session)
    items = src.get_items_by_work_type("roof_covering_replacement", limit=10)
    assert items and all({"id", "name", "unit", "quantity_per_unit"} <= i.keys() for i in items)
    assert {i["name"] for i in items} >= {"Metal roof sheet", "Roofing screw"}


def test_limit_caps_items(session):
    src = MaterialsDbPriceSource(session)
    assert len(src.get_items_by_work_type("roof_covering_replacement", limit=2)) == 2


def test_get_price_as_of_returns_price_and_date(session):
    src = MaterialsDbPriceSource(session)
    item = src.get_items_by_work_type("roof_covering_replacement", 10)[0]
    value, valid_from = src.get_price_as_of(item["id"], date(2026, 10, 16))
    assert isinstance(value, float) and value > 0
    assert valid_from == "2026-10-16"


def test_price_before_any_record_is_none(session):
    src = MaterialsDbPriceSource(session)
    item = src.get_items_by_work_type("facade_painting", 10)[0]
    assert src.get_price_as_of(item["id"], date(2000, 1, 1)) is None


def test_unknown_work_type_is_empty(session):
    assert MaterialsDbPriceSource(session).get_items_by_work_type("nope", 10) == []


# --- DB and CSV give the same answers (epic 5.4) -----------------------------
def test_csv_source_matches_db(session, tmp_path):
    items_csv, prices_csv = tmp_path / "items.csv", tmp_path / "prices.csv"
    export_csv(session, items_csv, prices_csv)
    db = MaterialsDbPriceSource(session)
    csv_src = CsvPriceSource(items_csv, prices_csv)

    for code in (w.code for w in WORK_TYPES):
        assert db.get_items_by_work_type(code, 10) == csv_src.get_items_by_work_type(code, 10)
        for item in db.get_items_by_work_type(code, 10):
            assert (db.get_price_as_of(item["id"], date(2026, 10, 16))
                    == csv_src.get_price_as_of(item["id"], date(2026, 10, 16)))
