"""PDF export of the report (task 7.6).

Section order follows the summary form of inspection results (Methodology No. 144, Додаток 6) and
the report outline of ДСТУ 9273:2024 (Додаток А), marked throughout as a preliminary assessment.
"""
import io
from datetime import date

import numpy as np
from fpdf import FPDF
from PIL import Image

from core import config
from core.imageio import LEGEND, overlay
from core.reference import (CONDITION_NAMES_UA, DAMAGE_NAMES_UA, DAMAGE_RECOMMENDATION_UA, DISCLAIMER_UA,
                            ESCALATION_UA, STRUCTURE_NAMES_UA, WORK_NAMES_UA)
from core.types import Report

FONT_DIR = config.ROOT / "resources" / "fonts"
LEGEND_UA = {"background": "фон", "facade": "фасад", "roof": "дах", "damaged facade": "пошкодження фасаду",
             "broken window": "пошкоджені вікна", "damaged roof": "пошкоджений дах"}


def _pct(x):
    return "не видно" if x is None else f"{x:.1%}"


def _num(x, unit=""):
    return "—" if x is None else f"{x:,.1f}{unit}".replace(",", " ")


def _uah(x):
    return f"{x:,.0f} грн".replace(",", " ")


class _PDF(FPDF):
    def header(self):
        self.set_font("dejavu", "", 8)
        self.set_text_color(120)
        self.cell(0, 5, "Попередня оцінка пошкоджень будівлі. Не є технічним обстеженням.", align="R")
        self.ln(7)
        self.set_text_color(0)

    def footer(self):
        self.set_y(-12)
        self.set_font("dejavu", "", 8)
        self.set_text_color(120)
        self.cell(0, 5, f"Сторінка {self.page_no()}", align="C")


def _table(pdf: FPDF, rows: list[list[str]], widths: list[float], header: bool = True):
    pdf.set_font("dejavu", "", 9)
    with pdf.table(col_widths=widths, text_align="LEFT", first_row_as_headings=header,
                   line_height=5.5) as t:
        for r in rows:
            row = t.row()
            for c in r:
                row.cell(str(c))
    pdf.ln(3)


def _h(pdf: FPDF, text: str):
    pdf.set_font("dejavu", "B", 12)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("dejavu", "", 10)


def _p(pdf: FPDF, text: str):
    pdf.set_font("dejavu", "", 10)
    pdf.multi_cell(0, 5, text, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def build_pdf(report: Report, images: dict[int, np.ndarray] | None = None) -> bytes:
    pdf = _PDF(format="A4")
    pdf.add_font("dejavu", "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("dejavu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    pdf.set_font("dejavu", "B", 16)
    pdf.cell(0, 10, "Звіт попередньої оцінки пошкоджень", new_x="LMARGIN", new_y="NEXT")
    mode = {"photo": "одне фото", "photos": "набір фото", "video": "відео"}.get(report.mode, report.mode)
    _p(pdf, f"Об'єкт: {report.case_id}   Дата: {date.today():%d.%m.%Y}   Вхідні дані: {mode}   "
            f"Оцінено різних видів: {report.views_assessed}")
    pdf.set_fill_color(255, 243, 205)
    pdf.set_font("dejavu", "", 9)
    pdf.multi_cell(0, 5, DISCLAIMER_UA, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # 1. Conclusion
    _h(pdf, "1. Висновок")
    d = report.decision
    if d is None:
        _p(pdf, "Шар прийняття рішень не запускався.")
    elif d.escalation == "insufficient_data":
        _p(pdf, f"Категорію не визначено (впевненість {d.confidence:.2f}). {ESCALATION_UA[d.escalation]}")
    else:
        _table(pdf, [
            ["Показник", "Значення", "Документ"],
            ["Категорія пошкоджень (основний результат)", f"{d.damage_category} — {DAMAGE_NAMES_UA[d.damage_category]}",
             "Методика № 144, Додаток 3"],
            ["Рекомендації щодо подальшої експлуатації", DAMAGE_RECOMMENDATION_UA[d.damage_category],
             "Методика № 144, Додаток 3"],
            ["Категорія технічного стану", f"{d.condition_category} — {CONDITION_NAMES_UA[d.condition_category]}",
             "ДСТУ 9273:2024, розділ 5"],
            ["Стан покрівлі за площею пошкоджень",
             "—" if d.roof_covering_category is None else str(d.roof_covering_category), "ДСТУ 9273:2024, табл. В.7.1"],
            ["Впевненість", f"{d.confidence:.2f}", ""],
        ], widths=[60, 75, 45])
        _p(pdf, ESCALATION_UA[d.escalation])

    # 2. Building parameters
    _h(pdf, "2. Параметри будівлі")
    b = report.building
    if b is None:
        _p(pdf, "Параметри не визначено.")
    else:
        auto = lambda f: "авто" if f in b.auto_detected else "введено"
        _table(pdf, [
            ["Параметр", "Значення", "Джерело"],
            ["Кількість поверхів", _num(b.floors and float(b.floors)).replace(".0", ""), auto("floors")],
            ["Висота", _num(b.height_m, " м"), b.height_source or ""],
            ["Ширина", _num(b.width_m, " м"), auto("width_m")],
            ["Глибина", _num(b.depth_m, " м"), auto("depth_m")],
            ["Тип конструкції", STRUCTURE_NAMES_UA.get(b.structure_type or "unknown", "невідомо"),
             auto("structure_type")],
            ["Тип даху", {"flat": "плаский", "pitched": "скатний"}.get(b.roof_type or "", "невідомо"),
             auto("roof_type")],
            ["Клас наслідків (оцінка)", f"{b.consequence_class or '—'} (~{b.occupants_estimate or '—'} осіб)",
             "ДБН В.1.2-14:2018, табл. 1"],
        ], widths=[60, 60, 60])
        if b.assumptions:
            _p(pdf, "Припущення: " + "; ".join(b.assumptions) + ".")

    # 3. Damage measurements
    _h(pdf, "3. Виміряні пошкодження")
    r = report.ratios
    a = report.areas
    _table(pdf, [
        ["Поверхня", "Частка видимої поверхні", "Найгірший вид", "Площа"],
        ["Пошкодження фасаду", _pct(r.damaged_facade), _pct(r.worst_facade_damage),
         _num(a.damaged_facade_m2 if a else None, " м²")],
        ["Пошкоджені вікна", _pct(r.broken_window), "", _num(a.broken_window_m2 if a else None, " м²")],
        ["Пошкодження даху", _pct(r.damaged_roof), _pct(r.worst_roof_damage),
         _num(a.damaged_roof_m2 if a else None, " м²")],
    ], widths=[50, 45, 40, 45])
    if r.damage_by_third:
        low, mid, up = r.damage_by_third
        _p(pdf, f"Розподіл пошкоджень фасаду по висоті: нижня третина {low:.0%}, середня {mid:.0%}, "
                f"верхня {up:.0%}.")
    if a:
        _p(pdf, f"Площа стін {_num(a.wall_area_m2, ' м²')}, площа даху {_num(a.roof_area_m2, ' м²')}.")

    # 4. Works and cost
    _h(pdf, "4. Перелік робіт і орієнтовна вартість")
    k = report.cost
    if d and d.works:
        rows = [["Робота", "Обсяг", "Вартість"]]
        for w in d.works:
            cost = sum(l.cost for l in k.lines if l.work_type == w.work_type) if k else None
            rows.append([WORK_NAMES_UA.get(w.work_type, w.work_type), _num(w.quantity, " м²"),
                         _uah(cost) if cost else "—"])
        _table(pdf, rows, widths=[90, 40, 50])
    if k:
        pdf.set_font("dejavu", "B", 11)
        pdf.multi_cell(0, 6, f"Орієнтовна вартість: від {_uah(k.low)} до {_uah(k.high)}", new_x="LMARGIN",
                       new_y="NEXT")
        if k.price_source:
            _p(pdf, f"Джерело цін: {k.price_source}.")
        _p(pdf, f"Ціни станом на {k.as_of}. Діапазон враховує похибку масштабу і кількість оцінених видів: "
                f"чим менше видів, тим ширший діапазон.")
        if k.skipped_works:
            _p(pdf, "Не враховано: " + "; ".join(k.skipped_works) + ".")

    # 5. Views
    if images:
        pdf.add_page()
        _h(pdf, "5. Види з розміткою")
        _p(pdf, "Кольори: " + ", ".join(LEGEND_UA[name] for name in LEGEND if name != "background") +
           " (див. легенду в інтерфейсі).")
        for view_id, image in list(images.items())[:4]:
            mask = report.masks.get(view_id)
            if mask is None:
                continue
            im = Image.fromarray(overlay(image, mask))
            im.thumbnail((1200, 1200))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=85)
            w = 180
            h = w * im.height / im.width
            if pdf.get_y() + h + 10 > pdf.h - 15:
                pdf.add_page()
            _p(pdf, f"Вид {view_id}")
            pdf.image(buf, w=w)
            pdf.ln(3)

    _h(pdf, "Джерела")
    _p(pdf, "ДСТУ 9273:2024 «Настанова щодо обстеження будівель і споруд для визначення та оцінювання їхнього "
            "технічного стану»; Методика проведення обстеження та оформлення його результатів, наказ "
            "Мінрозвитку № 144 від 06.08.2022; ДБН В.1.2-14:2018.")
    return bytes(pdf.output())
