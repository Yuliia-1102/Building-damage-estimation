"""Price history: lookup as of a date, and updates that keep old values (epic 5.3)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import LabourRate, Price, WorkType


def get_price_as_of(session: Session, material_id: int,
                    as_of: date | None = None) -> Price | None:
    """The price valid on `as_of` (latest row with valid_from <= as_of). Today by default."""
    if as_of is None:
        as_of = date.today()
    stmt = (select(Price)
            .where(Price.material_id == material_id, Price.valid_from <= as_of)
            .order_by(Price.valid_from.desc())
            .limit(1))
    return session.scalar(stmt)


def price_history(session: Session, material_id: int) -> list[Price]:
    stmt = select(Price).where(Price.material_id == material_id).order_by(Price.valid_from)
    return list(session.scalars(stmt))


def set_price(session: Session, material_id: int, value: float,
              valid_from: date | None = None, source: str = "manual",
              source_url: str | None = None, currency: str = "UAH") -> Price | None:
    """Record a price, preserving history. New value -> new row; same value -> no row."""
    if valid_from is None:
        valid_from = date.today()

    same_day = session.scalar(select(Price).where(
        Price.material_id == material_id, Price.valid_from == valid_from))
    if same_day is not None:
        if same_day.value == value and same_day.currency == currency:
            return None
        same_day.value = value
        same_day.currency = currency
        same_day.source = source
        same_day.source_url = source_url
        session.commit()
        return same_day

    latest = get_price_as_of(session, material_id, valid_from)
    if latest is not None and latest.value == value and latest.currency == currency:
        return None

    price = Price(material_id=material_id, value=value, currency=currency,
                  valid_from=valid_from, source=source, source_url=source_url)
    session.add(price)
    session.commit()
    return price


def get_labour_rate_as_of(session: Session, work_code: str, as_of: date | None = None) -> LabourRate | None:
    """The labour rate per m2 of work valid on `as_of`. Today by default."""
    if as_of is None:
        as_of = date.today()
    stmt = (select(LabourRate).join(WorkType)
            .where(WorkType.code == work_code, LabourRate.valid_from <= as_of)
            .order_by(LabourRate.valid_from.desc())
            .limit(1))
    return session.scalar(stmt)


def labour_history(session: Session, work_code: str) -> list[LabourRate]:
    stmt = (select(LabourRate).join(WorkType).where(WorkType.code == work_code)
            .order_by(LabourRate.valid_from))
    return list(session.scalars(stmt))


def set_labour_rate(session: Session, work_code: str, value: float, valid_from: date | None = None,
                    source: str = "manual", source_url: str | None = None,
                    currency: str = "UAH") -> LabourRate | None:
    """Record a labour rate, preserving history, with the same rules as set_price."""
    if valid_from is None:
        valid_from = date.today()
    work = session.scalar(select(WorkType).where(WorkType.code == work_code))
    if work is None:
        raise ValueError(f"unknown work type {work_code!r}")
    same_day = session.scalar(select(LabourRate).where(
        LabourRate.work_type_id == work.id, LabourRate.valid_from == valid_from))
    if same_day is not None:
        if same_day.value == value and same_day.currency == currency:
            return None
        same_day.value, same_day.currency, same_day.source, same_day.source_url = value, currency, source, source_url
        session.commit()
        return same_day
    latest = get_labour_rate_as_of(session, work_code, valid_from)
    if latest is not None and latest.value == value and latest.currency == currency:
        return None
    rate = LabourRate(work_type=work, value=value, currency=currency, valid_from=valid_from,
                      source=source, source_url=source_url)
    session.add(rate)
    session.commit()
    return rate
