"""Materials and prices administration - a separate Streamlit page (epic 5.6).

Admin tool, not part of the user flow. Sidebar navigation: Огляд / Матеріали /
Розцінки на роботи / Історія змін. All database work goes through pricedb helpers.

Access: if ADMIN_PASSWORD is set the page asks for it; otherwise dev mode with a warning.
Run:  uv run streamlit run ui/app.py   (then open "Ціни і матеріали" in the sidebar)
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from core import config  # noqa: E402
from core.reference import WORK_NAMES_UA  # noqa: E402
from pricedb import (  # noqa: E402
    add_material, labour_history, list_labour_rates, list_materials_with_price, open_db, price_history,
    update_labour_rate, update_price,
)

st.set_page_config(page_title="Ціни і матеріали", page_icon="🧱", layout="wide")
UNITS = ["kg", "l", "m2", "m", "pcs"]
NAV = {"Огляд": "📊", "Матеріали": "🧱", "Розцінки на роботи": "🔧", "Історія змін": "🕒"}

NAVY, MUTED, LINE, GREEN = "#1D3A5F", "#5B6B7F", "#E3E9F2", "#2F9E44"
CSS = f"""
<style>
.stApp {{background: #F4F7FB;}}
.block-container {{max-width: 1180px;}}
h1, h2, h3 {{color: {NAVY}; letter-spacing: -.01em;}}
button[kind="primary"] {{background: {NAVY}; border-color: {NAVY};}}
div[data-testid="stForm"] {{border: 1px solid {LINE}; border-radius: .9rem; background: #fff;
    box-shadow: 0 1px 3px rgba(16,42,67,.05);}}
.hero {{padding: 1.3rem 1.6rem; border-radius: 1rem; margin-bottom: 1.2rem;
        background: linear-gradient(120deg, #15314F 0%, #2C5282 100%); color: #EAF1F9;}}
.hero h1 {{color: #fff; font-size: 1.6rem; margin: 0 0 .25rem; padding: 0;}}
.hero p {{color: #C7D6E8; margin: 0; font-size: .92rem; max-width: 72ch;}}
.tiles {{display: flex; gap: .8rem; flex-wrap: wrap; margin-bottom: 1.2rem;}}
.tile {{flex: 1; min-width: 150px; background: #fff; border: 1px solid {LINE}; border-radius: .8rem;
        padding: .9rem 1.1rem; box-shadow: 0 1px 3px rgba(16,42,67,.05);}}
.tile .n {{font-size: 1.7rem; font-weight: 800; color: {NAVY}; line-height: 1.1;}}
.tile .l {{color: {MUTED}; font-size: .82rem; margin-top: .15rem;}}
.muted {{color: {MUTED}; font-size: .88rem;}}
section[data-testid="stSidebar"] {{background: #fff; border-right: 1px solid {LINE};}}
</style>
"""


def check_access() -> bool:
    expected = os.environ.get("ADMIN_PASSWORD")
    if not expected:
        st.warning("ADMIN_PASSWORD не задано: сторінка без захисту (режим розробки).")
        return True
    if st.session_state.get("admin_ok"):
        return True
    entered = st.text_input("Пароль адміністратора", type="password")
    if entered and entered == expected:
        st.session_state["admin_ok"] = True
        return True
    if entered:
        st.error("Неправильний пароль.")
    st.stop()


@st.cache_resource
def get_sessionmaker():
    return open_db(config.path("materials_db"))   # creates and seeds the DB on first use


def saved(result) -> None:
    (st.info if result is None else st.success)(
        "Ціна та сама — новий запис не потрібен." if result is None
        else "Збережено; попереднє значення лишилось в історії.")


# ---------- sections ----------
def overview(Session):
    with Session() as s:
        materials = list_materials_with_price(s)
        rates = list_labour_rates(s)
    priced = sum(1 for r in materials if r.price is not None)
    dates = [r.valid_from for r in materials if r.valid_from] + [r.valid_from for r in rates if r.valid_from]
    last = max(dates).isoformat() if dates else "—"
    st.markdown(
        '<div class="hero"><h1>🧱 Ціни і матеріали</h1>'
        '<p>Довідник матеріалів, цін і розцінок на роботи для кошторису. Ціни не перезаписуються: '
        'нова ціна додається з датою, стара лишається в історії.</p></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="tiles">'
        f'<div class="tile"><div class="n">{len(materials)}</div><div class="l">матеріалів</div></div>'
        f'<div class="tile"><div class="n">{priced}</div><div class="l">з цінами</div></div>'
        f'<div class="tile"><div class="n">{len(rates)}</div><div class="l">видів робіт</div></div>'
        f'<div class="tile"><div class="n">{last}</div><div class="l">остання зміна</div></div>'
        '</div>', unsafe_allow_html=True)
    st.subheader("Останні зміни")
    st.dataframe(changes_df(Session).head(8), hide_index=True, width="stretch")


def materials_section(Session):
    st.subheader("🧱 Матеріали")
    with Session() as s:
        rows = list_materials_with_price(s)
    df = pd.DataFrame([{"ID": r.id, "Матеріал": r.name, "Од.": r.unit, "Ціна, грн": r.price,
                        "Діє з": r.valid_from, "Джерело": r.source} for r in rows])

    f1, f2, f3, f4 = st.columns([3, 2, 2, 1])
    query = f1.text_input("Пошук за назвою", placeholder="напр. штукатурка", label_visibility="collapsed")
    units = f2.multiselect("Одиниці", UNITS, placeholder="Усі одиниці", label_visibility="collapsed")
    sort_map = {"за назвою": "Матеріал", "за ціною": "Ціна, грн", "за датою": "Діє з"}
    sort_by = f3.selectbox("Сортувати", list(sort_map), label_visibility="collapsed")
    descending = f4.toggle("↓", help="За спаданням")

    view = df.copy()
    if query:
        view = view[view["Матеріал"].str.contains(query, case=False, na=False)]
    if units:
        view = view[view["Од."].isin(units)]
    view = view.sort_values(sort_map[sort_by], ascending=not descending, na_position="last")

    event = st.dataframe(
        view, hide_index=True, width="stretch", selection_mode="single-row", on_select="rerun",
        key="mat_table",
        column_config={
            "Матеріал": st.column_config.TextColumn(width="large"),
            "Джерело": st.column_config.TextColumn(width="large"),
            "Ціна, грн": st.column_config.NumberColumn(format="localized"),
        })
    st.caption(f"Показано {len(view)} із {len(df)}. Клацніть рядок, щоб обрати матеріал для оновлення ціни.")

    sel_rows = event.selection.rows if event and event.selection else []
    selected = view.iloc[sel_rows[0]] if sel_rows else None
    if selected is not None:
        with st.expander(f"Деталі: {selected['Матеріал']}", expanded=True):
            st.write(f"**Одиниця:** {selected['Од.']}  ·  **Ціна:** {selected['Ціна, грн']} грн  ·  "
                     f"**Діє з:** {selected['Діє з']}")
            st.write(f"**Джерело:** {selected['Джерело']}")

    st.markdown("### Керування")
    t_price, t_add = st.tabs(["💰 Оновити ціну", "➕ Додати матеріал"])
    label_by_id = {f"{r.name} ({r.unit})": r.id for r in rows}
    with t_price:
        preset = 0
        if selected is not None:
            key = f"{selected['Матеріал']} ({selected['Од.']})"
            if key in label_by_id:
                preset = list(label_by_id).index(key)
        with st.form("update_price"):
            label = st.selectbox("Матеріал", list(label_by_id), index=preset)
            c1, c2 = st.columns(2)
            value = c1.number_input("Нова ціна за одиницю, грн", min_value=0.0, step=1.0)
            valid_from = c2.date_input("Діє з", value=date.today())
            source = st.text_input("Джерело", value="manual")
            if st.form_submit_button("Зберегти ціну", type="primary"):
                with Session() as s:
                    saved(update_price(s, label_by_id[label], value, valid_from, source))
    with t_add:
        with st.form("add_material", clear_on_submit=True):
            c1, c2 = st.columns([3, 1])
            name = c1.text_input("Назва матеріалу")
            unit = c2.selectbox("Одиниця", UNITS)
            if st.form_submit_button("Додати матеріал", type="primary"):
                try:
                    with Session() as s:
                        add_material(s, name, unit)
                    st.success(f"Додано: {name}")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


def labour_section(Session):
    st.subheader("🔧 Розцінки на роботи")
    st.caption("Вартість роботи (праці) за 1 м² виду робіт, без матеріалів.")
    with Session() as s:
        rows = list_labour_rates(s)
    df = pd.DataFrame([{"Код": r.code, "Робота": WORK_NAMES_UA.get(r.code, r.name),
                        "Ціна за м², грн": r.price, "Діє з": r.valid_from, "Джерело": r.source} for r in rows])
    q = st.text_input("Пошук за назвою роботи", placeholder="напр. покрівля", label_visibility="collapsed")
    view = df[df["Робота"].str.contains(q, case=False, na=False)] if q else df
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"Робота": st.column_config.TextColumn(width="large"),
                                "Ціна за м², грн": st.column_config.NumberColumn(format="localized")})
    names = {r.code: WORK_NAMES_UA.get(r.code, r.name) for r in rows}
    st.markdown("### Оновити розцінку")
    with st.form("update_labour"):
        code = st.selectbox("Робота", list(names), format_func=names.get)
        c1, c2 = st.columns(2)
        value = c1.number_input("Нова ціна за м², грн", min_value=0.0, step=1.0)
        valid_from = c2.date_input("Діє з", value=date.today())
        source = st.text_input("Джерело", value="manual")
        if st.form_submit_button("Зберегти розцінку", type="primary"):
            with Session() as s:
                saved(update_labour_rate(s, code, value, valid_from, source))


def changes_df(Session) -> pd.DataFrame:
    with Session() as s:
        materials = list_materials_with_price(s)
        rates = list_labour_rates(s)
        recs = []
        for m in materials:
            for p in price_history(s, m.id):
                recs.append({"Тип": "Матеріал", "Назва": m.name, "Діє з": p.valid_from,
                             "Ціна, грн": p.value, "Джерело": p.source})
        for r in rates:
            for h in labour_history(s, r.code):
                recs.append({"Тип": "Робота", "Назва": WORK_NAMES_UA.get(r.code, r.name),
                             "Діє з": h.valid_from, "Ціна, грн": h.value, "Джерело": h.source})
    df = pd.DataFrame(recs)
    return df.sort_values("Діє з", ascending=False) if not df.empty else df


def history_section(Session):
    st.subheader("🕒 Історія змін")
    df = changes_df(Session)
    if df.empty:
        st.info("Історія поки порожня.")
        return
    c1, c2 = st.columns([1, 3])
    kind = c1.selectbox("Тип", ["Усі", "Матеріал", "Робота"])
    q = c2.text_input("Пошук за назвою", placeholder="назва матеріалу або роботи", label_visibility="collapsed")
    view = df
    if kind != "Усі":
        view = view[view["Тип"] == kind]
    if q:
        view = view[view["Назва"].str.contains(q, case=False, na=False)]
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={"Ціна, грн": st.column_config.NumberColumn(format="localized")})
    st.caption(f"{len(view)} записів.")


def main():
    st.markdown(CSS, unsafe_allow_html=True)
    check_access()
    Session = get_sessionmaker()
    with st.sidebar:
        st.markdown("### ⚙️ Адміністрування")
        page = st.radio("Розділ", list(NAV), format_func=lambda k: f"{NAV[k]}  {k}",
                        label_visibility="collapsed")
    {"Огляд": overview, "Матеріали": materials_section,
     "Розцінки на роботи": labour_section, "Історія змін": history_section}[page](Session)


main()