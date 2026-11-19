"""Prices and materials: the same database and admin functions as the Streamlit page (pricedb.admin).

A new price never overwrites the old one: it is added with a date, so earlier reports can be reproduced.
The worker reads the same data/materials.db, so a saved price is used by the next assessment.
"""
from datetime import date
from functools import lru_cache
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from core import config
from core.reference import WORK_NAMES_UA
from pricedb import (Material, add_material, labour_history, list_labour_rates, list_materials_with_price,
                     open_db, price_history, update_labour_rate, update_price)
from web import audit
from web.db import session_scope
from web.templating import render

router = APIRouter()


def _admin_only(request: Request, action: str, object_id) -> HTMLResponse | None:
    """Prices change every later estimate, so only an administrator may change them (v2.0)."""
    user = request.state.user
    if user.is_admin:
        return None
    with session_scope() as s:
        audit.record(s, user, action, "price", object_id, result="denied", details="not an administrator")
    return HTMLResponse('<p>Змінювати ціни може лише адміністратор.</p><p><a href="/materials">Назад</a></p>',
                        status_code=403)


def _audit(request: Request, action: str, object_id, details: str) -> None:
    with session_scope() as s:
        audit.record(s, request.state.user, action, "price", object_id, details=details)

UNIT_NAMES = {"kg": "кг", "l": "л", "m2": "м²", "m3": "м³", "m": "м", "pcs": "шт."}


@lru_cache(maxsize=1)
def _sessions():
    return open_db(config.path("materials_db"))   # creates and seeds the database on first use


def _parse(value: str, valid_from: str) -> tuple[float, date]:
    try:
        number = float(value.replace(",", ".").replace(" ", ""))
    except ValueError:
        raise ValueError("Ціна має бути числом.")
    if number < 0:
        raise ValueError("Ціна не може бути від'ємною.")
    try:
        day = date.fromisoformat(valid_from) if valid_from else date.today()
    except ValueError:
        raise ValueError("Неправильна дата.")
    return number, day


def _back(tab: str, msg: str = "", err: str = "", **extra) -> RedirectResponse:
    query = f"tab={tab}" + "".join(f"&{k}={v}" for k, v in extra.items() if v)
    if msg:
        query += "&msg=" + quote_plus(msg)
    if err:
        query += "&err=" + quote_plus(err)
    return RedirectResponse(f"/materials?{query}", status_code=303)


@router.get("/materials")
def materials_page(request: Request):
    q = request.query_params
    tab = q.get("tab") if q.get("tab") in ("materials", "labour") else "materials"
    with _sessions()() as s:
        materials = list_materials_with_price(s)
        used_in = {m.id: sorted(WORK_NAMES_UA.get(link.work_type.code, link.work_type.name) for link in m.used_in)
                   for m in s.scalars(select(Material))}
        labour = [(r, WORK_NAMES_UA.get(r.code, r.name)) for r in list_labour_rates(s)]
        material_id = int(q["material"]) if q.get("material", "").isdigit() else (materials[0].id if materials else None)
        work_code = q.get("work") or (labour[0][0].code if labour else None)
        m_history = price_history(s, material_id) if material_id else []
        l_history = labour_history(s, work_code) if work_code else []
    return render("materials.html", request, tab=tab, materials=materials, used_in=used_in, labour=labour,
                  material_id=material_id, work_code=work_code, m_history=m_history, l_history=l_history,
                  units=UNIT_NAMES, today=date.today().isoformat(), msg=q.get("msg"), err=q.get("err"))


@router.post("/materials/price")
def save_price(request: Request, material_id: int = Form(...), value: str = Form(...),
               valid_from: str = Form(""), source: str = Form("")):
    if (denied := _admin_only(request, "price_changed", f"material:{material_id}")):
        return denied
    try:
        number, day = _parse(value, valid_from)
        with _sessions()() as s:
            saved = update_price(s, material_id, number, day, source.strip() or "оператор")
    except ValueError as e:
        return _back("materials", err=str(e), material=material_id)
    if saved is not None:
        _audit(request, "price_changed", f"material:{material_id}", f"{number} from {day.isoformat()}")
    msg = ("Ціна та сама, новий запис не потрібен." if saved is None
           else "Ціну збережено, попереднє значення лишилось в історії.")
    return _back("materials", msg=msg, material=material_id)


@router.post("/materials/new")
def new_material(request: Request, name: str = Form(...), unit: str = Form(...), value: str = Form(""),
                 source: str = Form("")):
    if (denied := _admin_only(request, "material_added", None)):
        return denied
    if unit not in UNIT_NAMES:
        return _back("materials", err="Невідома одиниця виміру.")
    try:
        with _sessions()() as s:
            if not name.strip():
                raise ValueError("Вкажіть назву матеріалу.")
            if s.scalar(select(Material).where(Material.name == name.strip())):
                raise ValueError(f"Матеріал «{name.strip()}» уже є.")
            material = add_material(s, name, unit)
            if value.strip():
                number, day = _parse(value, "")
                update_price(s, material.id, number, day, source.strip() or "оператор")
            material_id = material.id
    except ValueError as e:
        return _back("materials", err=str(e))
    _audit(request, "material_added", f"material:{material_id}", f"{name.strip()} ({unit})")
    return _back("materials", msg=f"Матеріал «{name.strip()}» додано.", material=material_id)


@router.post("/materials/labour")
def save_labour(request: Request, work_code: str = Form(...), value: str = Form(...),
                valid_from: str = Form(""), source: str = Form("")):
    if (denied := _admin_only(request, "labour_rate_changed", f"work:{work_code}")):
        return denied
    try:
        number, day = _parse(value, valid_from)
        with _sessions()() as s:
            saved = update_labour_rate(s, work_code, number, day, source.strip() or "оператор")
    except ValueError as e:
        return _back("labour", err=str(e), work=work_code)
    if saved is not None:
        _audit(request, "labour_rate_changed", f"work:{work_code}", f"{number} from {day.isoformat()}")
    msg = ("Розцінка та сама, новий запис не потрібен." if saved is None
           else "Розцінку збережено, попереднє значення лишилось в історії.")
    return _back("labour", msg=msg, work=work_code)
