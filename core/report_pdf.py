"""PDF export of the report (task 7.6).

Section order follows the summary form of inspection results (Methodology No. 144, Додаток 6) and
the report outline of ДСТУ 9273:2024 (Додаток А), marked throughout as a preliminary assessment.
"""
import io
import re
from datetime import date

import numpy as np
from fpdf import FPDF
from PIL import Image

from core import config
from core.imageio import LEGEND, overlay
from core.reference import (CONDITION_NAMES_UA, DAMAGE_NAMES_UA, DAMAGE_RECOMMENDATION_UA, DISCLAIMER_UA,
                            ESCALATION_UA, NOT_RESTORABLE_UA, STRUCTURE_NAMES_UA, UNITS_UA,
                            WORK_NAMES_UA)
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
    "depth assumed typical (end wall not seen)":
        "глибину прийнято типовою для житлового будинку (12 м, або ширина, якщо будівля вужча): торця не видно "
        "на знімках; виправте, якщо відома",
    "depth measured on the narrowest of the views (the end wall)":
        "глибину виміряно за найвужчим видом (торець будівлі)",
    "roof type unknown, flat roof assumed": "тип даху невідомий, прийнято плаский",
    "floors not readable and no reference object: dimensions unknown, enter them":
        "поверхи не читаються і немає еталонного об'єкта: розміри невідомі, введіть їх",
    "stub building parameters, not detected":
        "параметри будівлі не визначено автоматично, показано умовні значення; введіть справжні",
}
REFERENCE_UA = {"door": "двері", "car": "автомобіль", "person": "людина"}
_ASSUMPTION_PATTERNS = [
    (r"floors read on frame (\d+); not readable on frame\(s\) (.+)",
     lambda m: f"поверхи пораховано на кадрі {m[1]}; на кадрах {m[2]} їх не видно"),
    (r"floor count uncertain \(confidence ([\d.]+)\)",
     lambda m: f"кількість поверхів визначено неточно (впевненість {m[1]}); перевірте"),
    (r"floors not readable, height from a (\w+) of ([\d.]+) m",
     lambda m: f"поверхи не читаються; висоту оцінено за об'єктом «{REFERENCE_UA.get(m[1], m[1])}» "
               f"висотою {m[2]} м"),
]


def walls_seen_ua(a, fmt) -> str:
    """'1 200 м² з 4 170 м² (29%) — пошкодження оцінено лише на видимих стінах; інші сторони не оцінено'."""
    seen = a.visible_wall_area_m2 or a.wall_area_m2
    share = seen / a.wall_area_m2 if a.wall_area_m2 else 1
    text = f"{fmt(seen, ' м²')} з {fmt(a.wall_area_m2, ' м²')} усіх стін ({share:.0%})"
    if share < 0.9:
        text += " — пошкодження і вартість пораховано лише для видимих стін; інші сторони не оцінено"
    return text


def summary_ua(report: Report) -> str | None:
    """The result in one line, for the top of the report. None when there is no real decision (a stub is no result)."""
    d, k = report.decision, report.cost
    if d is None or d.is_stub:
        return None
    if d.escalation == "insufficient_data":
        return f"Категорію не визначено: недостатньо даних (впевненість {d.confidence:.2f})."
    parts = [f"Категорія пошкоджень {d.damage_category} ({DAMAGE_NAMES_UA[d.damage_category]})",
             f"технічний стан {d.condition_category} ({CONDITION_NAMES_UA[d.condition_category]})"]
    if d.damage_category == "III":
        parts.append("відновлення недоцільне, рекомендовано демонтаж")
    elif k and k.total > 0:
        parts.append(f"вартість від {_uah(k.low)} до {_uah(k.high)}")
    parts.append(f"впевненість {d.confidence:.2f}")
    return " · ".join(parts)


def cost_basis_ua(report: Report) -> list[str]:
    """What the cost is made of: materials against labour, and the damaged areas it was computed for."""
    k, a = report.cost, report.areas
    if k is None or k.total <= 0:
        return []
    split = f"Центральна оцінка {_uah(k.total)}: матеріали {_uah(k.materials)}"
    notes = [split + (f", робота {_uah(k.labour)}." if k.labour > 0 else " (розцінок на роботу немає).")]
    if a:
        areas = [f"{name} {_num(value, ' м²')}" for name, value in (
            ("пошкоджений фасад", a.damaged_facade_m2), ("вибиті вікна", a.broken_window_m2),
            ("пошкоджений дах", a.damaged_roof_m2)) if value]
        if areas:
            notes.append("Пораховано для площ: " + ", ".join(areas) + ".")
    return notes


WALL_STEPS_TITLE = "Як пораховано роботи на стінах"


def _ua_num(x: float, digits: int = 0) -> str:
    """12345.6 -> '12 346', 2.46 with digits=1 -> '2,5' (Ukrainian separators)."""
    return f"{x:,.{digits}f}".replace(",", " ").replace(".", ",")


def _m2(x: float) -> str:
    return _ua_num(x, 1 if x < 10 else 0) + " м²"


def wall_steps(d, building, areas) -> list[str]:
    """How the wall works follow from the damaged facade, step by step and in square metres, for a reader who
    checks the numbers: the window openings inside it, the wall destroyed through, the finish.
    The first line is the damaged area, the last one says where the shares come from."""
    from core.decision import wall_thickness
    f = d.facade
    total = areas.damaged_facade_m2 if areas else None
    w, x = f.window_openings_share, f.destroyed_wall_share
    t = wall_thickness(building)
    kind = STRUCTURE_NAMES_UA.get((building.structure_type if building else None) or "unknown", "невідомо")
    finish = "утеплення з декоративною штукатуркою" if f.insulated else "штукатурка"
    scaffolding = building is None or building.floors is None or building.floors > 1

    if total is None:      # dimensions unknown: the same steps in shares only
        lines = ["Площу пошкодженої ділянки фасаду не визначено (невідомі розміри будівлі), тому нижче — лише частки."]
        lines.append(f"1. Віконні прорізи — {w:.0%} пошкодженої ділянки. Їх пораховано як заміну вікон."
                     if w > 0 else "1. Віконних прорізів у пошкодженій ділянці немає.")
        lines.append(f"2. Решта — стіна. З неї {x:.0%} зруйновано наскрізь: розбирання, вивезення уламків і нова "
                     f"кладка (тип конструкції: {kind}, товщина стіни {_ua_num(t, 2)} м)."
                     if x > 0 else "2. Решта — стіна. Наскрізних руйнувань немає: стіну не розбирають і не "
                                   "перекладають.")
        lines.append(f"3. {finish.capitalize()} і фарбування — на всю пошкоджену стіну"
                     + (", з риштуванням." if scaffolding else "."))
    else:
        windows = total * w
        wall = total - windows
        destroyed = wall * x
        lines = [f"Пошкоджена ділянка фасаду: {_m2(total)}."]
        lines.append(f"1. З них {_m2(windows)} ({w:.0%}) — віконні прорізи у зруйнованій стіні. "
                     f"Їх пораховано як заміну вікон." if windows > 0
                     else "1. Віконних прорізів у пошкодженій ділянці немає.")
        if destroyed > 0:
            lines.append(f"2. Решта {_m2(wall)} — стіна. З неї {_m2(destroyed)} ({x:.0%}) зруйновано наскрізь: "
                         f"розбирання, вивезення уламків і нова кладка — {_ua_num(destroyed * t, 1)} м³ "
                         f"(тип конструкції: {kind}, товщина стіни {_ua_num(t, 2)} м).")
        else:
            lines.append(f"2. Решта {_m2(wall)} — стіна. Наскрізних руйнувань немає: стіну не розбирають і не "
                         f"перекладають.")
        lines.append(f"3. {finish.capitalize()} і фарбування — на всі {_m2(wall)} стіни"
                     + (", з риштуванням на ту саму площу." if scaffolding else "."))
    lines.append("Частки віконних прорізів і наскрізних руйнувань визначено автоматично за фото.")
    return lines


def assumption_ua(text: str) -> str:
    """A building assumption in Ukrainian, for the report and the operator's page."""
    if text in ASSUMPTIONS_UA:
        return ASSUMPTIONS_UA[text]
    for pattern, ua in _ASSUMPTION_PATTERNS:
        m = re.fullmatch(pattern, text)
        if m:
            return ua(m)
    return text


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


STUB_UA = ("Категорію не визначено: автоматичну оцінку для цих знімків не завершено. "
           "Пошкодження на фото позначено, але категорію, перелік робіт і вартість потрібно визначити повторною "
           "оцінкою або під час обстеження.")
NO_QUANTITY_UA = "не визначено"

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
    summary = summary_ua(report)
    if summary:
        pdf.set_font("dejavu", "B", 10)
        pdf.multi_cell(0, 5, summary, new_x="LMARGIN", new_y="NEXT")
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
        _p(pdf, "Перелік робіт і вартість не визначено: вони залежать від категорії пошкоджень.")
        k = None
    elif d.damage_category == "III":
        _p(pdf, NOT_RESTORABLE_UA)
    if d and not d.is_stub and d.works:
        rows = [["Робота", "Обсяг", "Вартість"]]
        for w in d.works:
            cost = sum(l.cost for l in k.lines if l.work_type == w.work_type) if k else None
            rows.append([WORK_NAMES_UA.get(w.work_type, w.work_type),
                         _num(w.quantity, " " + UNITS_UA.get(w.unit, w.unit)) if w.quantity is not None
                         else NO_QUANTITY_UA, _uah(cost) if cost else "—"])
        _table(pdf, rows, widths=[90, 40, 50])
        if any(w.quantity is None for w in d.works):
            _p(pdf, "Обсяг «не визначено»: цю поверхню видно на знімках не повністю (наприклад, дах лише смужкою), "
                    "тому її площу і вартість не пораховано. Потрібні знімки з іншого ракурсу або обмір на місці.")
        if d.facade:
            _sub(pdf, WALL_STEPS_TITLE)
            for line in wall_steps(d, report.building, report.areas):
                _p(pdf, line)
    if k:
        pdf.set_font("dejavu", "B", 11)
        pdf.multi_cell(0, 6, f"Орієнтовна вартість: від {_uah(k.low)} до {_uah(k.high)}", new_x="LMARGIN",
                       new_y="NEXT")
        notes = cost_basis_ua(report)
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
