"""A work without quantity, the page refresh after processing, full-size views, Ukrainian report texts, and
the prices page."""
import json
from pathlib import Path

import pytest

from core.report_pdf import STUB_UA, assumption_ua
from web import service


def test_work_without_quantity_does_not_break_the_page(client, create, pump, db):
    aid = create(["roof_1.jpg", "roof_2.jpg"], "дах смужкою")
    pump()
    with db() as s:
        path = Path(service.get(s, aid).result_dir) / "result.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["report"]["decision"]["works"].append(
        {"work_type": "roof_covering_replacement", "damage_class": "damaged_roof", "quantity": None, "unit": "m2"})
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    r = client.get(f"/applications/{aid}")
    assert r.status_code == 200 and "не визначено" in r.text


def test_progress_asks_for_a_full_reload_when_done(client, create, pump):
    aid = create("house.jpg", "x")
    assert "HX-Refresh" not in client.get(f"/applications/{aid}/progress").headers
    pump()
    assert client.get(f"/applications/{aid}/progress").headers.get("HX-Refresh") == "true"


def test_views_open_in_full_size(client, create, pump):
    aid = create("house.jpg", "x")
    pump()
    assert 'target="_blank"' in client.get(f"/applications/{aid}").text


def test_report_texts_are_ukrainian_and_name_no_service():
    assert "Gemini" not in STUB_UA
    assert assumption_ua("stub building parameters, not detected").startswith("параметри будівлі")
    assert assumption_ua("floor count uncertain (confidence 0.40)") == \
        "кількість поверхів визначено неточно (впевненість 0.40); перевірте"
    assert "двері" in assumption_ua("floors not readable, height from a door of 2.1 m")
    assert assumption_ua("floors read on frame 3; not readable on frame(s) 1, 2") == \
        "поверхи пораховано на кадрі 3; на кадрах 1, 2 їх не видно"


@pytest.fixture
def prices(tmp_path, monkeypatch):
    """The prices page on a temporary copy of the materials database, never the real data/materials.db."""
    from pricedb import open_db
    from web.routes import materials
    sessions = open_db(tmp_path / "materials.db")
    monkeypatch.setattr(materials, "_sessions", lambda: sessions)
    return sessions


def test_prices_page_saves_a_price_and_keeps_history(client, prices):
    from pricedb import list_materials_with_price, price_history
    r = client.get("/materials")
    assert r.status_code == 200 and "Поточні ціни матеріалів" in r.text
    assert client.get("/materials?tab=labour").status_code == 200
    with prices() as s:
        m = list_materials_with_price(s)[0]
        before = len(price_history(s, m.id))
    r = client.post("/materials/price", data={"material_id": m.id, "value": f"{(m.price or 0) + 10:.2f}".replace(".", ","),
                                              "valid_from": "2030-01-01", "source": "тест"})
    assert "Ціну збережено" in r.text
    with prices() as s:
        assert len(price_history(s, m.id)) == before + 1
    r = client.post("/materials/price", data={"material_id": m.id, "value": "abc"})
    assert "Ціна має бути числом" in r.text


def test_prices_page_adds_a_material(client, prices):
    r = client.post("/materials/new", data={"name": "Тестовий матеріал", "unit": "kg", "value": "12"})
    assert "Матеріал «Тестовий матеріал» додано" in r.text and "<td>Тестовий матеріал</td>" in r.text
    r = client.post("/materials/new", data={"name": "Тестовий матеріал", "unit": "kg"})
    assert "уже є" in r.text


def test_labour_rate_is_saved(client, prices):
    from pricedb import labour_history, list_labour_rates
    with prices() as s:
        code = list_labour_rates(s)[0].code
        before = len(labour_history(s, code))
    client.post("/materials/labour", data={"work_code": code, "value": "999", "valid_from": "2030-01-01"})
    with prices() as s:
        assert len(labour_history(s, code)) == before + 1
