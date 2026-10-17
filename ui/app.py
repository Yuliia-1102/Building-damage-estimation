"""Streamlit interface (epic 7). A thin layer: it collects input, calls core.pipeline and renders the Report.

Run:  uv run streamlit run ui/app.py

Streamlit re-runs this whole script on every click, so (task 7.5): models are loaded once with
st.cache_resource, segmentation results live in st.session_state, and editing a building parameter
only re-runs evaluate(), never the model.
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
from core.report_pdf import LEGEND_UA, build_pdf  # noqa: E402

st.set_page_config(page_title="Оцінка пошкоджень будівлі", page_icon="🏚️", layout="wide")

PHOTO_TYPES = ["jpg", "jpeg", "png", "webp"]
VIDEO_TYPES = ["mp4", "mov", "avi", "mkv", "webm"]
MODES = {
    "Одне фото": "Найгрубіша оцінка: видно лише один бік будівлі, тому діапазон вартості найширший.",
    "Набір фото": "Кілька боків будівлі: точніше, ніж одне фото. Кожне фото вважається окремим видом.",
    "Відео": "Система сама вибирає кілька найрізніших різких кадрів з обльоту. Обробка довша.",
}


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


# ---------- helpers ----------

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
    bar = st.progress(0.0, text="Підготовка…")

    video_info = None
    if mode == "Відео":
        bar.progress(0.05, text="Нарізка відео і відбір найрізніших кадрів…")
        case, video_info = case_from_video(folder / Path(files[0].name).name, folder, get_quick_segmenter())
    else:
        case = case_from_paths(folder.name, [folder / Path(f.name).name for f in files])

    def progress(done, total, text):
        bar.progress(0.1 + 0.75 * done / max(total, 1), text=text.replace("segmenting view", "Сегментація виду")
                     .replace("of", "з").replace("segmentation done", "Сегментацію завершено"))

    seg = segment_case(case, segmenter, progress)
    bar.progress(0.9, text="Параметри будівлі, класифікація і вартість…")
    report = evaluate(seg, building_estimator=building_estimator, decision_layer=decision_layer,
                      price_source=get_prices())
    bar.progress(1.0, text="Готово")
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


def pct(x):
    return "не видно" if x is None else f"{x:.1%}"


def num(x, unit=""):
    return "—" if x is None else f"{x:,.1f}{unit}".replace(",", " ")


def uah(x):
    return f"{x:,.0f} грн".replace(",", " ")


# ---------- screens ----------

def upload_screen():
    st.header("Оцінка пошкоджень будівлі")
    st.caption(DISCLAIMER_UA)
    mode = st.radio("Що завантажуєте?", list(MODES), horizontal=True)
    st.info(MODES[mode])
    max_mb = config.get("ui", "max_upload_mb")
    files = st.file_uploader(
        "Файли", type=VIDEO_TYPES if mode == "Відео" else PHOTO_TYPES,
        accept_multiple_files=(mode == "Набір фото"), help=f"До {max_mb} МБ на файл")
    files = [files] if files and not isinstance(files, list) else (files or [])
    too_big = [f.name for f in files if f.size > max_mb * 1024 * 1024]
    if too_big:
        st.error("Завеликі файли: " + ", ".join(too_big))
    if mode == "Набір фото" and len(files) == 1:
        st.warning("Для одного фото оберіть режим «Одне фото».")
    if st.button("Оцінити", type="primary", disabled=not files or bool(too_big)):
        run_assessment(mode, files)


def report_screen():
    report = st.session_state.report
    seg = st.session_state.seg
    building_layer, decision_layer, online = get_language_layers()
    _, real_seg = get_segmenter()
    if not online:
        sources = {getattr(building_layer, "last_source", None), getattr(decision_layer, "last_source", None)}
        if "stub" in sources:
            st.warning("Gemini вимкнено, а для цього випадку немає збережених відповідей: параметри будівлі "
                       "і класифікація — фіксовані заглушки. Увімкніть Gemini в бічній панелі для реальної оцінки.")
        else:
            st.info("Gemini вимкнено: показано збережені раніше відповіді Gemini для цього випадку (без запитів).")
    if not real_seg:
        st.warning("Ваги моделі сегментації не знайдено: маски — заглушки.")
    for e in report.errors:
        st.error(f"Крок не виконано: {e}")

    d = report.decision
    st.subheader("Висновок")
    if d is None:
        st.write("Класифікацію не виконано.")
    elif d.escalation == "insufficient_data":
        st.error(ESCALATION_UA[d.escalation] + f" (впевненість {d.confidence:.2f})")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Категорія пошкоджень", f"{d.damage_category} — {DAMAGE_NAMES_UA[d.damage_category]}",
                  help="Методика № 144, Додаток 3. Основний результат для черговості обстежень.")
        c2.metric("Технічний стан", f"{d.condition_category} — {CONDITION_NAMES_UA[d.condition_category]}",
                  help="ДСТУ 9273:2024, розділ 5")
        c3.metric("Впевненість", f"{d.confidence:.2f}")
        (st.success if d.escalation == "confirmed" else st.warning)(ESCALATION_UA[d.escalation])
        st.write(f"Рекомендація: {DAMAGE_RECOMMENDATION_UA[d.damage_category]}.")
        if d.roof_covering_category:
            st.write(f"Стан покрівлі за площею пошкоджень (ДСТУ 9273, табл. В.7.1): категорія "
                     f"{d.roof_covering_category}.")

    r, a = report.ratios, report.areas
    st.subheader("Виміряні пошкодження")
    st.dataframe(pd.DataFrame([
        {"Поверхня": "Пошкодження фасаду", "Частка видимої поверхні": pct(r.damaged_facade),
         "Найгірший вид": pct(r.worst_facade_damage), "Найгірша секція фасаду": pct(r.worst_section_damage),
         "Площа, м²": a.damaged_facade_m2 if a else None},
        {"Поверхня": "Пошкоджені вікна", "Частка видимої поверхні": pct(r.broken_window),
         "Найгірший вид": "", "Найгірша секція фасаду": "", "Площа, м²": a.broken_window_m2 if a else None},
        {"Поверхня": "Пошкодження даху", "Частка видимої поверхні": pct(r.damaged_roof),
         "Найгірший вид": pct(r.worst_roof_damage), "Найгірша секція фасаду": "",
         "Площа, м²": a.damaged_roof_m2 if a else None},
    ]), hide_index=True, width="stretch")
    notes = ["Найгірша секція — третина ширини фасаду з найбільшою часткою пошкоджень в одному виді: "
             "показує зруйновану секцію, яку середнє по фасаду розмиває."]
    if r.damage_by_third:
        low, mid, up = r.damage_by_third
        notes.append(f"Пошкодження фасаду по висоті: нижня третина {low:.0%}, середня {mid:.0%}, верхня {up:.0%}.")
    st.caption(" ".join(notes))

    k = report.cost
    st.subheader("Орієнтовна вартість відновлення")
    if k and k.total > 0:
        st.markdown(f"### від {uah(k.low)} до {uah(k.high)}")
        st.caption(f"Оцінено різних видів: {report.views_assessed}. Ціни станом на {k.as_of}"
                   + (f"; джерело: {k.price_source}" if k.price_source else "")
                   + ". Чим менше видів, тим ширший діапазон.")
    else:
        st.write("Вартість не розраховано: невідомі розміри будівлі або немає цін.")
    if d and d.works:
        rows = []
        for w in d.works:
            cost = sum(l.cost for l in k.lines if l.work_type == w.work_type) if k else None
            rows.append({"Робота": WORK_NAMES_UA.get(w.work_type, w.work_type), "Обсяг, м²": w.quantity,
                         "Вартість, грн": cost})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if k and k.lines:
            with st.expander("Розрахунок по позиціях"):
                st.dataframe(pd.DataFrame([{
                    "Робота": WORK_NAMES_UA.get(l.work_type, l.work_type), "Позиція": l.item_name,
                    "Кількість": round(l.quantity, 2), "Од.": l.unit, "Ціна": l.unit_price,
                    "Сума": round(l.cost), "Ціна від": l.price_date} for l in k.lines]),
                    hide_index=True, width="stretch")
        if k and k.skipped_works:
            st.caption("Не враховано: " + "; ".join(k.skipped_works))

    st.subheader("Параметри будівлі")
    b = report.building
    if b is None:
        st.write("Параметри не визначено.")
    else:
        st.caption("Позначка «авто» означає, що значення визначено автоматично. Помилка на один поверх "
                   "лінійно змінює всю вартість — перевірте і виправте за потреби.")
        auto = lambda f: " (авто)" if f in b.auto_detected else ""
        with st.form("params"):
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
            if st.form_submit_button("Перерахувати"):
                new = {"floors": int(floors), "floor_height_m": float(floor_h), "width_m": width or None,
                       "depth_m": depth or None, "roof_type": roof, "structure_type": structure}
                old = {k: getattr(b, k) for k in new}
                changes = {k: v for k, v in new.items() if v != old[k]}
                if changes:
                    recalculate(changes)
                    st.rerun()
        if st.session_state.get("recalc_time") is not None:
            st.caption(f"Перераховано за {st.session_state.recalc_time:.2f} с без повторної сегментації.")
        st.write(f"Висота {num(b.height_m, ' м')} ({b.height_source or '—'}); клас наслідків "
                 f"{b.consequence_class or '—'} (~{b.occupants_estimate or '—'} осіб, оцінка за ДБН В.1.2-14:2018).")
        if b.assumptions:
            st.caption("Припущення: " + "; ".join(b.assumptions))

    st.subheader("Звіт у PDF")
    if st.button("Підготувати PDF"):
        st.session_state.pdf = build_pdf(report, seg.images)
    if st.session_state.get("pdf"):
        st.download_button("Завантажити PDF", st.session_state.pdf, file_name=f"zvit_{report.case_id}.pdf",
                           mime="application/pdf")


def masks_screen():
    report = st.session_state.report
    seg = st.session_state.seg
    info = st.session_state.get("video_info")
    if info:
        st.info(f"Відео: нарізано {info['extracted']} кадрів (1 за секунду), відкинуто розмитих {info['blurred']}. "
                f"Відео поділено на рівні відрізки, щоб охопити всі сторони будівлі; у кожному перевірено кандидатів "
                f"(усього {info['checked']}) і взято той, де будівлю видно найкраще. Обрано видів: {info['selected']}.")
        if info.get("rejected"):
            st.caption("Відхилені кандидати: " + "; ".join(
                f"{name} — " + reason.replace("building cut off on", "будівля обрізана з").replace("sides", "боків")
                .replace("no building", "будівлі не видно") for name, reason in info["rejected"].items()))
    legend = " ".join(f"<span style='background:rgb{tuple(c)};padding:2px 8px;border-radius:4px;"
                      f"color:{'#fff' if sum(c) < 400 else '#000'}'>{LEGEND_UA[n]}</span>"
                      for n, c in LEGEND.items() if n != "background")
    st.markdown(legend, unsafe_allow_html=True)
    for vid, err in report.skipped_frames.items():
        st.error(f"Вид {vid} пропущено: {err}")
    for f in report.frames:
        st.markdown(f"**Вид {f.view_id}**")
        c1, c2 = st.columns([3, 2])
        c1.image(overlay(seg.images[f.view_id], seg.masks[f.view_id]), width="stretch")
        c2.dataframe(pd.DataFrame([
            {"Показник": "Пошкодження фасаду", "Значення": pct(f.damaged_facade_ratio)},
            {"Показник": "Пошкоджені вікна", "Значення": pct(f.broken_window_ratio)},
            {"Показник": "Найгірша секція фасаду", "Значення": pct(f.worst_section)},
            {"Показник": "Пошкодження даху", "Значення": pct(f.damaged_roof_ratio)},
            {"Показник": "Фасад займає кадру", "Значення": pct(f.facade_share)},
            {"Показник": "Дах займає кадру", "Значення": pct(f.roof_share)},
        ]), hide_index=True, width="stretch")
        c2.write(("✅" if f.facade_usable else "❌") + " враховано для фасаду   " +
                 ("✅" if f.roof_usable else "❌") + " враховано для даху")
        for reason in f.excluded_reasons:
            c2.caption("Відсіяно: " + reason.replace("facade", "фасад").replace("roof", "дах")
                       .replace("of frame", "кадру"))


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


from dotenv import load_dotenv  # noqa: E402
load_dotenv(config.ROOT / ".env")
has_key = bool(os.environ.get("GEMINI_API_KEY"))
st.sidebar.toggle("Gemini API (платні запити)", key="use_gemini", disabled=not has_key,
                  help="Вимкнено: жодних запитів, використовуються збережені відповіді або заглушки. "
                       "Увімкнено: кожна нова оцінка — 2 запити, кожне редагування параметрів — 1 запит.")
if not has_key:
    st.sidebar.caption("Ключ GEMINI_API_KEY не задано.")
# With the materials database, prices are edited on the separate "Materials admin" page (ui/pages/).
sections = ["Оцінка"] + (["Адміністрування цін"] if config.get("prices", "source") == "csv" else [])
page = st.sidebar.radio("Розділ", sections)
if page == "Оцінка":
    upload_screen()
    if "report" in st.session_state:
        tab_report, tab_masks = st.tabs(["Звіт", "Маски і метрики"])
        with tab_report:
            report_screen()
        with tab_masks:
            masks_screen()
else:
    admin_screen()
