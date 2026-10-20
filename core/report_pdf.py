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
                            ESCALATION_UA, STRUCTURE_NAMES_UA, UNITS_UA, WORK_NAMES_UA)
from core.provenance import consequence_note, parameter_rows
from core.types import Report

FONT_DIR = config.ROOT / "resources" / "fonts"
COLOR_NAMES_UA = {"facade": "зелений", "roof": "оранжевий", "damaged facade": "фіолетовий",
                  "broken window": "синій", "damaged roof": "червоний"}
LEGEND_UA = {"background": "фон", "facade": "фасад", "roof": "дах", "damaged facade": "пошкодження фасаду",
             "broken window": "пошкоджені вікна", "damaged roof": "пошкоджений дах"}


ASSUMPTIONS_UA = {
    "depth assumed equal to width (no corner view used)":
        "глибину прийнято рівною ширині: торця будівлі не видно на знімках; виправте, якщо відома",
    "depth measured on the narrowest of the views (the end wall)":
        "глибину виміряно за найвужчим видом (торець будівлі)",
    "roof type unknown, flat roof assumed": "тип даху невідомий, прийнято плаский",
    "floors not readable and no reference object: dimensions unknown, enter them":
        "поверхи не читаються і немає еталонного об'єкта: розміри невідомі, введіть їх",
}


def walls_seen_ua(a, fmt) -> str:
    """'1 200 м² з 4 170 м² (29%) — пошкодження оцінено лише на видимих стінах; інші сторони не оцінено'."""
    seen = a.visible_wall_area_m2 or a.wall_area_m2
    share = seen / a.wall_area_m2 if a.wall_area_m2 else 1
    text = f"{fmt(seen, ' м²')} з {fmt(a.wall_area_m2, ' м²')} усіх стін ({share:.0%})"
    if share < 0.9:
        text += " — пошкодження і вартість пораховано лише для видимих стін; інші сторони не оцінено"
    return text


def facade_notes(d, building) -> list[str]:
    """The model's assessment of the damaged facade and how the wall works follow from it."""
    from core.decision import wall_thickness
    f = d.facade
    t = wall_thickness(building)
    kind = STRUCTURE_NAMES_UA.get((building.structure_type if building else None) or "unknown", "невідомо")
    return [
        f"Віконні прорізи: {f.window_openings_share:.0%} пошкодженої площі фасаду (оцінка моделі за фото; "
        f"сегментація позначає вікна у зруйнованих стінах як пошкодження фасаду). Вони пораховані у віконних "
        f"роботах, а не в стінових.",
        f"Зруйновано наскрізь: {f.destroyed_wall_share:.0%} решти стіни (оцінка моделі). На цій частині: "
        f"розбирання і вивіз уламків, кладка в м³ за товщиною стіни {t:.2f} м ({kind}), далі оздоблення.",
        f"Оздоблення і фарбування: на всій пошкодженій стіні; "
        f"{'система утеплення з декоративною штукатуркою' if f.insulated else 'штукатурка'}.",
    ]


def assumption_ua(text: str) -> str:
    return ASSUMPTIONS_UA.get(text, text)


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


TABLE_FILL = (246, 242, 235)


def _table(pdf: FPDF, rows: list[list[str]], widths: list[float], header: bool = True):
    pdf.set_font("dejavu", "", 9)
    pdf.set_fill_color(*TABLE_FILL)
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


def _sub(pdf: FPDF, text: str):
    pdf.set_font("dejavu", "B", 10)
    pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("dejavu", "", 10)


def _kv(pdf: FPDF, rows: list[tuple[str, str]], widths=(70, 110)):
    """Two columns, no header: label and value."""
    pdf.set_font("dejavu", "", 9)
    pdf.set_fill_color(*TABLE_FILL)
    with pdf.table(col_widths=widths, text_align="LEFT", first_row_as_headings=False, line_height=5.5) as t:
        for label, value in rows:
            row = t.row()
            pdf.set_font("dejavu", "B", 9)
            row.cell(label)
            pdf.set_font("dejavu", "", 9)
            row.cell(value)
    pdf.ln(3)


def _bullets(pdf: FPDF, points: list[str]):
    """One point per line; the words before the first colon are bold."""
    for text in points:
        label, sep, rest = text.partition(": ")
        pdf.set_x(pdf.l_margin)
        pdf.set_font("dejavu", "", 10)
        pdf.cell(5, 5, "•")
        body = f"**{label}:** {rest}" if sep else text
        pdf.multi_cell(0, 5, body, markdown=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.8)
    pdf.ln(1.5)


def _legend(pdf: FPDF):
    """One line per class: a colour swatch and its name."""
    pdf.set_font("dejavu", "", 9)
    for name, rgb in LEGEND.items():
        if name == "background":
            continue
        y = pdf.get_y()
        pdf.set_fill_color(*rgb)
        pdf.rect(pdf.l_margin, y + 0.8, 8, 3.6, style="F")
        pdf.set_x(pdf.l_margin + 10)
        pdf.cell(0, 5.2, f"{LEGEND_UA[name]} — {COLOR_NAMES_UA[name]}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


STUB_UA = "Категорії не визначено: модель рішень не запускалась (Gemini вимкнено, збереженої відповіді для цих даних немає). Увімкніть Gemini і повторіть оцінку."

SOURCES = [
    ("Методика проведення обстеження та оформлення його результатів, наказ Мінрозвитку № 144 від 06.08.2022 — "
     "категорії пошкоджень (Додаток 3)", "https://zakon.rada.gov.ua/laws/show/z0898-22"),
    ("ДСТУ 9273:2024 «Настанова щодо обстеження будівель і споруд для визначення та оцінювання їхнього технічного "
     "стану» — категорії технічного стану (розділ 5)",
     "https://online.budstandart.com/ua/catalog/doc-page.html?id_doc=106902"),
    ("ДБН В.1.2-14:2018 «Система забезпечення надійності та безпеки будівельних об'єктів» — класи наслідків",
     "https://zakon.isu.net.ua/sites/default/files/normdocs/tekst_dbn_v.1.2-14_2018_sistema_zabezpechennya_nadiynosti_ta_.pdf"),
]



def build_pdf(report: Report, images: dict[int, np.ndarray] | None = None) -> bytes:
    pdf = _PDF(format="A4")
    pdf.add_font("dejavu", "", str(FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("dejavu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    pdf.set_font("dejavu", "B", 16)
    pdf.cell(0, 10, "Звіт попередньої оцінки пошкоджень", new_x="LMARGIN", new_y="NEXT")
    mode = {"photo": "одне фото", "photos": "набір фото", "video": "відео"}.get(report.mode, report.mode)
    _kv(pdf, [("Об'єкт", report.case_id), ("Дата", f"{date.today():%d.%m.%Y}"), ("Вхідні дані", mode),
              ("Оцінено різних видів", str(report.views_assessed))], widths=(50, 130))
    pdf.set_fill_color(255, 243, 205)
    pdf.set_font("dejavu", "", 9)
    pdf.multi_cell(0, 5, DISCLAIMER_UA, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # 1. Views
    if images:
        _h(pdf, "1. Будівля і маски пошкоджень")
        _sub(pdf, "Кольори масок")
        _legend(pdf)
        _p(pdf, "Сірим позначено інші будівлі в кадрі: вони не оцінюються.")
        # two views per row, 88 mm wide each
        shown = [(v, im) for v, im in list(images.items())[:6] if report.masks.get(v) is not None]
        for row in range(0, len(shown), 2):
            pair = []
            for view_id, image in shown[row:row + 2]:
                im = Image.fromarray(overlay(image, report.masks[view_id], excluded=report.excluded.get(view_id)))
                im.thumbnail((900, 900))
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                pair.append((view_id, buf, 88 * im.height / im.width))
            h = max(p[2] for p in pair)
            if pdf.get_y() + h + 10 > pdf.h - 15:
                pdf.add_page()
            y = pdf.get_y()
            for i, (view_id, buf, _) in enumerate(pair):
                x = pdf.l_margin + i * 92
                pdf.set_xy(x, y)
                pdf.set_font("dejavu", "", 8)
                pdf.cell(88, 4, f"Вид {view_id}")
                pdf.image(buf, x=x, y=y + 5, w=88)
            pdf.set_xy(pdf.l_margin, y + h + 8)
        pdf.ln(2)

    # 2. Building parameters
    _h(pdf, "2. Параметри будівлі")
    b = report.building
    if b is None:
        _p(pdf, "Параметри не визначено.")
    else:
        _table(pdf, [["Параметр", "Значення", "Звідки значення"]] + [list(r) for r in parameter_rows(b)],
               widths=[45, 45, 90])
        _kv(pdf, [("Клас наслідків (ДБН В.1.2-14:2018, табл. 1)", consequence_note(b))], widths=(55, 125))
        notes = [assumption_ua(a) for a in b.assumptions if not a.startswith("depth ")]
        if notes:
            _sub(pdf, "Припущення")
            _bullets(pdf, notes)

    # 3. Damage measurements
    _h(pdf, "3. Виміряні пошкодження")
    r = report.ratios
    a = report.areas
    _table(pdf, [
        ["Поверхня", "Пошкоджено в середньому по всіх видах", "З найгіршого боку", "Площа пошкоджень"],
        ["Фасад", _pct(r.damaged_facade), _pct(r.worst_facade_damage) + (f" (вид {r.worst_facade_view})"
                                                                         if r.worst_facade_view else ""),
         _num(a.damaged_facade_m2 if a else None, " м²")],
        ["Вікна", _pct(r.broken_window), "", _num(a.broken_window_m2 if a else None, " м²")],
        ["Дах", _pct(r.damaged_roof), _pct(r.worst_roof_damage) + (f" (вид {r.worst_roof_view})"
                                                                   if r.worst_roof_view else ""),
         _num(a.damaged_roof_m2 if a else None, " м²")],
    ], widths=[30, 55, 50, 45])
    extra = []
    if r.worst_section_damage is not None:
        extra.append(("Найбільш зруйнована ділянка фасаду",
                      f"{_pct(r.worst_section_damage)} її площі пошкоджено (ділянка завширшки в третину фасаду, "
                      f"вид {r.worst_section_view}). Показує локальне руйнування, яке середнє по фасаду "
                      f"розмиває; категорію визначає найгірша частина будівлі (ДСТУ 9273, п. 5.3)."))
    if r.damage_by_third:
        low, mid, up = r.damage_by_third
        extra.append(("Як пошкодження розподілені по висоті",
                      f"нижні поверхи {low:.0%}, середні {mid:.0%}, верхні {up:.0%} усіх пошкоджень фасаду. "
                      f"Руйнування нижніх поверхів небезпечніше для всієї будівлі (ДСТУ 9273, п. 11.26)."))
    if a:
        extra.append(("Оцінені стіни", walls_seen_ua(a, _num)))
        if a.roof_area_m2 is not None:
            extra.append(("Площа даху", _num(a.roof_area_m2, " м²")))
    if r.roof_partly_seen:
        extra.append(("Дах", "видно лише смугою, оцінка приблизна"))
    if r.broken_window is not None and r.broken_window < 0.03 and (r.damaged_facade or 0) > 0.3:
        extra.append(("Вікна", "у зруйнованих ділянках вікна не виділяються окремо і враховані в пошкодженнях "
                               "фасаду"))
    if extra:
        _kv(pdf, extra, widths=(55, 125))

    # 4. Conclusion
    _h(pdf, "4. Висновок")
    d = report.decision
    if d is None or d.is_stub:
        pdf.set_font("dejavu", "B", 10)
        pdf.set_text_color(180, 30, 30)
        pdf.multi_cell(0, 5, STUB_UA, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
        pdf.ln(2)
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
        pdf.set_font("dejavu", "B", 10)
        pdf.multi_cell(0, 5, ESCALATION_UA[d.escalation], new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)


    # 5. Works and cost
    _h(pdf, "5. Перелік робіт і орієнтовна вартість")
    k = report.cost
    if d is None or d.is_stub:
        _p(pdf, "Перелік робіт і вартість не визначено: вони залежать від рішення моделі.")
        k = None
    if d and not d.is_stub and d.works:
        rows = [["Робота", "Обсяг", "Вартість"]]
        for w in d.works:
            cost = sum(l.cost for l in k.lines if l.work_type == w.work_type) if k else None
            rows.append([WORK_NAMES_UA.get(w.work_type, w.work_type),
                         _num(w.quantity, " " + UNITS_UA.get(w.unit, w.unit)), _uah(cost) if cost else "—"])
        _table(pdf, rows, widths=[90, 40, 50])
        if d.facade:
            _sub(pdf, "Як складено роботи на стінах")
            _bullets(pdf, facade_notes(d, report.building))
    if k:
        pdf.set_font("dejavu", "B", 11)
        pdf.multi_cell(0, 6, f"Орієнтовна вартість: від {_uah(k.low)} до {_uah(k.high)}", new_x="LMARGIN",
                       new_y="NEXT")
        notes = []
        if k.price_source:
            notes.append(f"Джерело цін: {k.price_source}, ціни станом на {k.as_of}.")
        notes.append(f"Діапазон: враховує похибку масштабу і кількість оцінених видів ({report.views_assessed}); "
                     f"що менше видів, то ширший діапазон.")
        if k.skipped_works:
            notes.append("Не враховано: " + "; ".join(k.skipped_works) + ".")
        _bullets(pdf, notes)

    _h(pdf, "Джерела")
    for title, url in SOURCES:
        pdf.set_font("dejavu", "", 9)
        pdf.multi_cell(0, 4.6, "• " + title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(30, 80, 200)
        pdf.set_font("dejavu", "", 7)
        pdf.set_x(pdf.l_margin + 3)
        pdf.cell(0, 4.6, url, link=url, new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)
        pdf.ln(1)
    return bytes(pdf.output())
