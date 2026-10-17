"""Streamlit interface (epic 7). A thin layer: it collects input, calls core.pipeline and renders the Report.

Run:  uv run streamlit run ui/app.py

Streamlit re-runs this whole script on every click, so (task 7.5): models are loaded once with
st.cache_resource, segmentation results live in st.session_state, and editing a building parameter
only re-runs evaluate(), never the model.

The report reads top to bottom in the order an inspector checks it: the views with the masks (is the
segmentation right?), the building parameters (are the dimensions right?), the measured damage, the
conclusion by the standards, the works and the cost, the PDF.
"""
import copy
import hashlib
import os
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config  # noqa: E402
from core.building import best_frame_for_floors  # noqa: E402
from core.cache import CachedSegmenter  # noqa: E402
from core.case import case_from_paths, case_from_video  # noqa: E402
from core.imageio import LEGEND, overlay  # noqa: E402
from core.pipeline import evaluate, segment_case  # noqa: E402
from core.reference import (CONDITION_NAMES_UA, DAMAGE_NAMES_UA, DAMAGE_RECOMMENDATION_UA,  # noqa: E402
                            DISCLAIMER_UA, ESCALATION_UA, STRUCTURE_NAMES_UA, WORK_NAMES_UA)
from core.report_pdf import STUB_UA, COLOR_NAMES_UA, LEGEND_UA, assumption_ua, build_pdf  # noqa: E402

st.set_page_config(page_title="Оцінка пошкоджень будівлі", page_icon="🏚️", layout="wide")

PHOTO_TYPES = ["jpg", "jpeg", "png", "webp"]
VIDEO_TYPES = ["mp4", "mov", "avi", "mkv", "webm"]
MODES = {
    "Одне фото": ("📷", "Найшвидше, але видно лише один бік будівлі: діапазон вартості найширший."),
    "Набір фото": ("🗂️", "Кілька боків будівлі. Кожне фото — окремий вид, категорію визначає найгірша частина."),
    "Відео": ("🎥", "Обліт дроном. Система сама вибирає по одному найкращому кадру з кожного відрізка обльоту."),
}
DAMAGE_COLORS = {"I": "green", "II": "orange", "III": "red"}
CONDITION_COLORS = {1: "green", 2: "blue", 3: "orange", 4: "red"}

CSS = """
<style>
.block-container {padding-top: 2rem; max-width: 1280px;}
h1, h2, h3 {letter-spacing: -0.01em;}
.hero {padding: 1.4rem 1.6rem; border-radius: 0.9rem; margin-bottom: 1.2rem;
       background: linear-gradient(120deg, #1F2933 0%, #3E4C59 100%); color: #F7F5F2;}
.hero h1 {color: #F7F5F2; font-size: 1.9rem; margin: 0 0 .3rem 0; padding: 0;}
.hero p {color: #CBD2D9; margin: 0; font-size: .95rem;}
.section-title {display: flex; align-items: center; gap: .6rem; margin: 1.6rem 0 .6rem 0;}
.section-title .num {background: #C2410C; color: white; border-radius: 50%; width: 1.9rem; height: 1.9rem;
                     display: inline-flex; align-items: center; justify-content: center; font-weight: 700;}
.section-title .txt {font-size: 1.35rem; font-weight: 700;}
.legend span {display: inline-block; padding: .15rem .6rem; border-radius: 1rem; margin: 0 .35rem .35rem 0;
              font-size: .85rem; font-weight: 600;}
.big-cost {font-size: 2.1rem; font-weight: 800; color: #1F2933; line-height: 1.1;}
.muted {color: #616E7C; font-size: .88rem;}
.kv {display: flex; justify-content: space-between; border-bottom: 1px dashed #E4E0DA; padding: .3rem 0;}
.kv b {font-weight: 600;}
div[data-testid="stMetricValue"] {font-size: 1.5rem;}
</style>
"""


# ---------- resources loaded once per server (task 7.5.1) ----------

@st.cache_resource(show_spinner="Завантаження моделі сегментації…")
def get_segmenter():
    weights = config.path("weights")
    if not weights.exists():
        from models.stub import StubSegmenter
        return StubSegmenter(), False
    from models.dinov2_unet import DinoV2Segmenter
    return CachedSegmenter(DinoV2Segmenter(), model_id=weights.stem), True


def get_quick_segmenter():
    """Quick masks for choosing video frames; shares the weights with the full segmenter."""
    from core.cache import quick_segmenter
    segmenter, real = get_segmenter()
    return quick_segmenter(segmenter) if real else None


def gemini_on() -> bool:
    """Paid Gemini requests only when the toggle in the sidebar is on (it is off by default)."""
    return st.session_state.get("use_gemini", False)


@st.cache_resource
def _layers(online: bool):
    if online:
        from models.gemini_building import GeminiBuildingEstimator
        from models.gemini_decision import GeminiDecisionLayer
        return GeminiBuildingEstimator(), GeminiDecisionLayer()
    from models.offline import CachedOrStubBuilding, CachedOrStubDecision
    return CachedOrStubBuilding(), CachedOrStubDecision()


def get_language_layers():
    """(building estimator, decision layer, online). Offline: cached Gemini answers, otherwise stubs."""
    online = gemini_on()
    return *_layers(online), online


def get_prices():
    from models.price_source import default_price_source
    return default_price_source()


# ---------- actions ----------

def save_uploads(files) -> Path:
    digest = hashlib.sha256(b"".join(f.getvalue() for f in files)).hexdigest()[:16]
    folder = config.path("cases") / "_uploads" / digest
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        (folder / Path(f.name).name).write_bytes(f.getvalue())
    return folder


def run_assessment(mode: str, files) -> None:
    folder = save_uploads(files)
    segmenter, _ = get_segmenter()
    building_estimator, decision_layer, _ = get_language_layers()
    with st.status("Оцінюємо будівлю…", expanded=True) as status:
        video_info = None
        if mode == "Відео":
            st.write("🎞️ Нарізаємо відео і відбираємо найкращі кадри з кожного відрізка обльоту…")
            case, video_info = case_from_video(folder / Path(files[0].name).name, folder, get_quick_segmenter())
        else:
            case = case_from_paths(folder.name, [folder / Path(f.name).name for f in files])
        bar = st.progress(0.0)

        def progress(done, total, text):
            bar.progress(done / max(total, 1), text=f"🧩 Сегментація: вид {min(done + 1, total)} з {total}")

        seg = segment_case(case, segmenter, progress)
        st.write("🏢 Параметри будівлі, категорії за нормативами, роботи і вартість…")
        report = evaluate(seg, building_estimator=building_estimator, decision_layer=decision_layer,
                          price_source=get_prices())
        status.update(label="Готово", state="complete", expanded=False)
    st.session_state.update(seg=seg, report=report, video_info=video_info, pdf=None, recalc_time=None)


def recalculate(changes: dict) -> None:
    """Task 4.5 / 7.4: re-run only evaluate() with the corrected parameters."""
    from models.gemini_building import recompute
    seg, report = st.session_state.seg, st.session_state.report
    _, decision_layer, _ = get_language_layers()
    building = copy.deepcopy(report.building)
    for k, v in changes.items():
        setattr(building, k, v)
    masks = [seg.masks[f.view_id] for f in seg.frames]
    frame = building.source_frame if building.source_frame is not None else best_frame_for_floors(masks)
    building = recompute(building, masks[frame], set(changes))
    t = time.perf_counter()
    report = evaluate(seg, building=building, decision_layer=decision_layer, price_source=get_prices())
    st.session_state.update(report=report, pdf=None, recalc_time=time.perf_counter() - t)


# ---------- formatting ----------

def pct(x):
    return "не видно" if x is None else f"{x:.0%}"


def num(x, unit=""):
    return "—" if x is None else f"{x:,.1f}{unit}".replace(",", " ").replace(".0" + unit, unit)


def uah(x):
    return f"{x:,.0f} грн".replace(",", " ")


def section(n: int, title: str) -> None:
    st.markdown(f"<div class='section-title'><span class='num'>{n}</span><span class='txt'>{title}</span></div>",
                unsafe_allow_html=True)


def legend_html() -> str:
    chips = []
    for name, c in LEGEND.items():
        if name == "background":
            continue
        fg = "#fff" if sum(c) < 450 else "#1F2933"
        chips.append(f"<span style='background:rgb{tuple(c)};color:{fg}'>{LEGEND_UA[name]}</span>")
    return "<div class='legend'>" + "".join(chips) + "</div>"


def kv(label: str, value: str) -> str:
    return f"<div class='kv'><span>{label}</span><b>{value}</b></div>"


# ---------- screens ----------

def hero():
    st.markdown("<div class='hero'><h1>🏚️ Оцінка пошкоджень будівлі</h1>"
                "<p>Фото або відео пошкодженої будівлі → маски пошкоджень, параметри будівлі, категорії за "
                "Методикою № 144 і ДСТУ 9273:2024, перелік робіт і орієнтовна вартість відновлення.</p></div>",
                unsafe_allow_html=True)


def upload_screen():
    with st.container(border=True):
        c1, c2 = st.columns([2, 3], vertical_alignment="center")
        mode = c1.segmented_control("Що завантажуєте?", list(MODES), default="Набір фото",
                                    format_func=lambda m: f"{MODES[m][0]} {m}") or "Набір фото"
        c2.caption(MODES[mode][1])
        max_mb = config.get("ui", "max_upload_mb")
        files = st.file_uploader(
            "Файли", type=VIDEO_TYPES if mode == "Відео" else PHOTO_TYPES, label_visibility="collapsed",
            accept_multiple_files=(mode == "Набір фото"), help=f"До {max_mb} МБ на файл")
        files = [files] if files and not isinstance(files, list) else (files or [])
        too_big = [f.name for f in files if f.size > max_mb * 1024 * 1024]
        if too_big:
            st.error("Завеликі файли: " + ", ".join(too_big))
        if mode == "Набір фото" and len(files) == 1:
            st.warning("Для одного фото оберіть режим «Одне фото».")
        if st.button("Оцінити будівлю", type="primary", icon="🔎", disabled=not files or bool(too_big),
                     width="stretch"):
            run_assessment(mode, files)
            st.rerun()
    st.caption(DISCLAIMER_UA)


def source_notice(report):
    building_layer, decision_layer, online = get_language_layers()
    _, real_seg = get_segmenter()
    if not online:
        sources = {getattr(building_layer, "last_source", None), getattr(decision_layer, "last_source", None)}
        if "stub" in sources:
            st.warning("Gemini вимкнено, а для цього випадку немає збережених відповідей: параметри будівлі і "
                       "категорії — фіксовані заглушки. Увімкніть Gemini в бічній панелі для реальної оцінки.",
                       icon="⚠️")
    if not real_seg:
        st.warning("Ваги моделі сегментації не знайдено: маски — заглушки.", icon="⚠️")
    for e in report.errors:
        st.error(f"Крок не виконано: {e}")


def views_section(report, seg):
    section(1, "Будівля і маски пошкоджень")
    info = st.session_state.get("video_info")
    if info:
        st.caption(f"🎥 З відео нарізано {info['extracted']} кадрів (1 за секунду). Обліт поділено на рівні відрізки, "
                   f"у кожному перевірено кандидатів (усього {info['checked']}) і взято кадр, де будівлю видно "
                   f"найкраще: обрано {info['selected']} видів з різних сторін.")
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.markdown(legend_html(), unsafe_allow_html=True)
    show_mask = c2.toggle("Показувати маску", value=True)
    for vid, err in report.skipped_frames.items():
        st.error(f"Вид {vid} пропущено: {err}")
    frames = report.frames
    worst = {report.ratios.worst_section_view, report.ratios.worst_facade_view}
    for row in range(0, len(frames), 2):
        cols = st.columns(2)
        for col, f in zip(cols, frames[row:row + 2]):
            with col.container(border=True):
                img = seg.images[f.view_id]
                st.image(overlay(img, seg.masks[f.view_id]) if show_mask else img, width="stretch")
                tag = " · найгірший вид" if f.view_id in worst else ""
                damaged = None if f.damaged_facade_ratio is None else f.damaged_facade_ratio + f.broken_window_ratio
                st.markdown(f"**Вид {f.view_id}**{tag}  \n"
                            f"<span class='muted'>фасад пошкоджено {pct(damaged)} · найгірша секція "
                            f"{pct(f.worst_section)} · дах {pct(f.damaged_roof_ratio)}</span>",
                            unsafe_allow_html=True)
                if not f.facade_usable or f.excluded_reasons:
                    st.caption("Не враховано: " + "; ".join(
                        r.replace("facade", "фасад").replace("roof", "дах").replace("of frame", "кадру")
                        for r in f.excluded_reasons))


def building_section(report):
    section(2, "Параметри будівлі")
    b = report.building
    if b is None:
        st.info("Параметри не визначено.")
        return
    c = st.columns(4)
    c[0].metric("Поверхів", b.floors or "—")
    c[1].metric("Висота", num(b.height_m, " м"))
    c[2].metric("Ширина × глибина", f"{num(b.width_m)} × {num(b.depth_m)} м" if b.width_m else "—")
    c[3].metric("Клас наслідків", b.consequence_class or "—",
                help=f"ДБН В.1.2-14:2018, табл. 1; оцінка ~{b.occupants_estimate or '—'} осіб за площею")
    st.markdown(
        f"<span class='muted'>Тип конструкції: <b>{STRUCTURE_NAMES_UA.get(b.structure_type or 'unknown')}</b> · "
        f"дах: <b>{ {'flat': 'плаский', 'pitched': 'скатний'}.get(b.roof_type or '', 'невідомо')}</b> · "
        f"визначено автоматично: {', '.join(sorted(b.auto_detected)) or '—'}</span>", unsafe_allow_html=True)
    if b.assumptions:
        st.caption("Припущення: " + "; ".join(assumption_ua(x) for x in b.assumptions))

    with st.expander("✏️ Виправити параметри і перерахувати", expanded=False):
        st.caption("Помилка на один поверх лінійно змінює всю вартість. Сегментація не перезапускається: "
                   "перераховуються лише площі, рішення і вартість.")
        auto = lambda f: " (авто)" if f in b.auto_detected else ""
        with st.form("params", border=False):
            c1, c2, c3 = st.columns(3)
            floors = c1.number_input("Поверхів" + auto("floors"), 1, 60, b.floors or 1)
            floor_h = c2.number_input("Висота поверху, м", 2.0, 6.0, float(b.floor_height_m), 0.1)
            width = c3.number_input("Ширина, м" + auto("width_m"), 0.0, 500.0, float(b.width_m or 0), 0.5)
            c4, c5, c6 = st.columns(3)
            depth = c4.number_input("Глибина, м" + auto("depth_m"), 0.0, 500.0, float(b.depth_m or 0), 0.5)
            roof_opts = ["flat", "pitched"]
            roof = c5.selectbox("Дах" + auto("roof_type"), roof_opts,
                                index=roof_opts.index(b.roof_type) if b.roof_type in roof_opts else 0,
                                format_func={"flat": "плаский", "pitched": "скатний"}.get)
            types = list(STRUCTURE_NAMES_UA)
            structure = c6.selectbox("Тип конструкції" + auto("structure_type"), types,
                                     index=types.index(b.structure_type) if b.structure_type in types else
                                     types.index("unknown"), format_func=STRUCTURE_NAMES_UA.get)
            if st.form_submit_button("Перерахувати", type="primary"):
                new = {"floors": int(floors), "floor_height_m": float(floor_h), "width_m": width or None,
                       "depth_m": depth or None, "roof_type": roof, "structure_type": structure}
                old = {k: getattr(b, k) for k in new}
                changes = {k: v for k, v in new.items() if v != old[k]}
                if changes:
                    with st.spinner("Перераховуємо…"):
                        recalculate(changes)
                    st.rerun()
    if st.session_state.get("recalc_time") is not None:
        st.success(f"Перераховано за {st.session_state.recalc_time:.1f} с без повторної сегментації.", icon="✅")


def damage_section(report):
    section(3, "Виміряні пошкодження")
    r, a = report.ratios, report.areas
    c = st.columns(4)
    c[0].metric("Фасад пошкоджено", pct(r.damaged_facade), help="В середньому по всіх видах")
    c[1].metric("Найбільш зруйнована ділянка фасаду", pct(r.worst_section_damage),
                help="Ділянка завширшки в третину фасаду з найбільшою часткою пошкоджень на одному виді. "
                     "Показує локальне руйнування, яке середнє розмиває; категорію визначає найгірша частина "
                     "будівлі (ДСТУ 9273, п. 5.3)")
    c[2].metric("Вікна пошкоджено", pct(r.broken_window))
    c[3].metric("Дах пошкоджено", pct(r.damaged_roof),
                help="Дах видно лише смугою, оцінка приблизна" if r.roof_partly_seen else None)
    rows = [
        {"Поверхня": "Фасад", "В середньому по всіх видах": pct(r.damaged_facade),
         "З найгіршого боку": pct(r.worst_facade_damage),
         "Площа пошкоджень, м²": round(a.damaged_facade_m2) if a and a.damaged_facade_m2 else None},
        {"Поверхня": "Вікна", "В середньому по всіх видах": pct(r.broken_window), "З найгіршого боку": "",
         "Площа пошкоджень, м²": round(a.broken_window_m2) if a and a.broken_window_m2 else None},
        {"Поверхня": "Дах", "В середньому по всіх видах": pct(r.damaged_roof),
         "З найгіршого боку": pct(r.worst_roof_damage),
         "Площа пошкоджень, м²": round(a.damaged_roof_m2) if a and a.damaged_roof_m2 else None},
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    notes = []
    if r.damage_by_third:
        low, mid, up = r.damage_by_third
        notes.append(f"По висоті: нижні поверхи {low:.0%}, середні {mid:.0%}, верхні {up:.0%} усіх пошкоджень "
                     f"фасаду (руйнування нижніх поверхів небезпечніше, ДСТУ 9273, п. 11.26).")
    if a:
        notes.append(f"Площа стін {num(a.wall_area_m2, ' м²')}, даху {num(a.roof_area_m2, ' м²')}.")
    if notes:
        st.caption(" ".join(notes))


def conclusion_section(report):
    section(4, "Висновок")
    d = report.decision
    if d is None or d.is_stub:
        st.error(STUB_UA, icon="⛔")
        return
    if d.escalation == "insufficient_data":
        st.error(ESCALATION_UA[d.escalation] + f" (впевненість {d.confidence:.2f})")
        return
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1:
            st.caption("Категорія пошкоджень · Методика № 144, Додаток 3")
            st.badge(f"{d.damage_category} — {DAMAGE_NAMES_UA[d.damage_category]}",
                     color=DAMAGE_COLORS[d.damage_category])
            st.markdown(f"<span class='muted'>Рекомендація: {DAMAGE_RECOMMENDATION_UA[d.damage_category]}</span>",
                        unsafe_allow_html=True)
        with c2:
            st.caption("Технічний стан · ДСТУ 9273:2024, розділ 5")
            st.badge(f"{d.condition_category} — {CONDITION_NAMES_UA[d.condition_category]}",
                     color=CONDITION_COLORS[d.condition_category])
            if d.roof_covering_category:
                st.markdown(f"<span class='muted'>Покрівля за площею пошкоджень (табл. В.7.1): категорія "
                            f"{d.roof_covering_category}</span>", unsafe_allow_html=True)
        with c3:
            st.metric("Впевненість", f"{d.confidence:.2f}")
        (st.success if d.escalation == "confirmed" else st.warning)(ESCALATION_UA[d.escalation])



def cost_section(report):
    section(5, "Роботи і орієнтовна вартість")
    d, k = report.decision, report.cost
    if d is None or d.is_stub:
        st.info("Перелік робіт і вартість не визначено: вони залежать від рішення моделі.")
        return
    c1, c2 = st.columns([2, 3])
    with c1.container(border=True):
        if k and k.total > 0:
            st.caption("Орієнтовна вартість відновлення")
            st.markdown(f"<div class='big-cost'>{uah(k.low)}<br>— {uah(k.high)}</div>", unsafe_allow_html=True)
            st.caption(f"Ціни станом на {k.as_of}" + (f", джерело: {k.price_source}" if k.price_source else "")
                       + f". Оцінено видів: {report.views_assessed}; що менше видів, то ширший діапазон.")
        else:
            st.info("Вартість не розраховано: невідомі розміри будівлі або немає цін. "
                    "Вкажіть параметри в розділі 2.")
    with c2:
        if d and d.works:
            rows = []
            for w in d.works:
                cost = sum(l.cost for l in k.lines if l.work_type == w.work_type) if k else None
                rows.append({"Робота": WORK_NAMES_UA.get(w.work_type, w.work_type),
                             "Обсяг, м²": round(w.quantity) if w.quantity else None,
                             "Вартість, грн": round(cost) if cost else None})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                         column_config={"Вартість, грн": st.column_config.NumberColumn(format="localized")})
    if k and k.lines:
        with st.expander("Розрахунок по позиціях: матеріали і робота"):
            st.dataframe(pd.DataFrame([{
                "Робота": WORK_NAMES_UA.get(l.work_type, l.work_type),
                "Позиція": "робота (праця)" if l.item_name == "labour" else l.item_name,
                "Кількість": round(l.quantity, 1), "Од.": l.unit, "Ціна, грн": l.unit_price,
                "Сума, грн": round(l.cost), "Ціна від": l.price_date} for l in k.lines]),
                hide_index=True, width="stretch")
    if k and k.skipped_works:
        st.caption("Не враховано: " + "; ".join(k.skipped_works))


def pdf_section(report, seg):
    section(6, "Звіт у PDF")
    c1, c2 = st.columns([1, 3], vertical_alignment="center")
    if c1.button("Підготувати PDF", icon="📄", width="stretch"):
        with st.spinner("Формуємо PDF…"):
            st.session_state.pdf = build_pdf(report, seg.images)
    if st.session_state.get("pdf"):
        c2.download_button("Завантажити PDF", st.session_state.pdf, file_name=f"zvit_{report.case_id}.pdf",
                           mime="application/pdf", icon="⬇️", type="primary")
    else:
        c2.caption("Звіт за зведеною формою Методики № 144: фото з розміткою, параметри, виміри, висновок, "
                   "роботи і вартість, джерела нормативів.")


def report_screen():
    report, seg = st.session_state.report, st.session_state.seg
    source_notice(report)
    views_section(report, seg)
    building_section(report)
    damage_section(report)
    conclusion_section(report)
    cost_section(report)
    pdf_section(report, seg)


def admin_screen():
    st.header("Адміністрування цін")
    prices = get_prices()
    st.caption(f"Джерело: {prices.label}. Ціни не перезаписуються: нова ціна додається з датою, стара "
               f"залишається в історії, тож попередні звіти можна відтворити.")
    st.dataframe(pd.DataFrame(prices.current_prices()).rename(columns={
        "id": "ID", "name": "Матеріал", "unit": "Од.", "price": "Ціна, грн", "valid_from": "Діє з",
        "history": "Записів в історії"}), hide_index=True, width="stretch")
    names = {m["id"]: m["name"] for m in prices.current_prices()}
    c1, c2 = st.columns(2)
    with c1.form("new_price"):
        st.markdown("**Нова ціна**")
        mid = st.selectbox("Матеріал", list(names), format_func=names.get)
        value = st.number_input("Ціна за одиницю, грн", 0.0, 1e6, 0.0, 0.5)
        valid_from = st.date_input("Діє з", date.today())
        source = st.text_input("Джерело ціни")
        if st.form_submit_button("Додати ціну") and value > 0:
            prices.add_price(mid, value, valid_from, source or "manual")
            st.success("Ціну додано, попередня збережена в історії.")
            st.rerun()
    with c2.form("new_material"):
        st.markdown("**Новий матеріал**")
        name = st.text_input("Назва")
        unit = st.text_input("Одиниця виміру", "m2")
        if st.form_submit_button("Додати матеріал") and name:
            prices.add_material(name, unit)
            st.success("Матеріал додано.")
            st.rerun()
    mid = st.selectbox("Історія цін", list(names), format_func=names.get, key="hist")
    st.dataframe(pd.DataFrame(prices.price_history(mid), columns=["Діє з", "Ціна, грн"]), hide_index=True)


# ---------- page ----------

st.markdown(CSS, unsafe_allow_html=True)
from dotenv import load_dotenv  # noqa: E402
load_dotenv(config.ROOT / ".env")
has_key = bool(os.environ.get("GEMINI_API_KEY"))
with st.sidebar:
    st.markdown("### 🏚️ Оцінка пошкоджень")
    st.toggle("Gemini API (платні запити)", key="use_gemini", disabled=not has_key,
              help="Вимкнено: жодних запитів, використовуються збережені відповіді або заглушки. "
                   "Увімкнено: кожна нова оцінка — 2 запити, кожне редагування параметрів — 1 запит.")
    if not has_key:
        st.caption("Ключ GEMINI_API_KEY не задано.")
    sections = ["Оцінка"] + (["Адміністрування цін"] if config.get("prices", "source") == "csv" else [])
    page = st.radio("Розділ", sections, label_visibility="collapsed") if len(sections) > 1 else "Оцінка"
    st.divider()
    st.caption("Кольори масок: " + ", ".join(f"{LEGEND_UA[n]} — {COLOR_NAMES_UA[n]}"
                                             for n in LEGEND if n != "background") + ".")
    if "report" in st.session_state and st.button("Нова оцінка", icon="↩️", width="stretch"):
        for key in ("report", "seg", "video_info", "pdf", "recalc_time"):
            st.session_state.pop(key, None)
        st.rerun()

if page == "Оцінка":
    hero()
    if "report" in st.session_state:
        report_screen()
    else:
        upload_screen()
else:
    admin_screen()
