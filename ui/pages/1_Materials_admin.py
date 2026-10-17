"""Materials and prices administration - a separate Streamlit page (epic 5.6).

An admin tool, not part of the user flow: Streamlit shows every file in ui/pages/ as its own entry in
the sidebar, beside the main app (ui/app.py).

Access: if ADMIN_PASSWORD is set, the page asks for it; otherwise it runs in dev mode with a warning.

Run:  uv run streamlit run ui/app.py   (then open "Materials admin" in the sidebar)
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


def check_access() -> bool:
    """Password gate. Dev mode (no password) if ADMIN_PASSWORD is unset."""
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
    st.info("Ціна та сама — новий запис не потрібен.") if result is None else \
        st.success("Ціну збережено, попереднє значення лишилось в історії.")


def materials_tab(Session) -> None:
    with Session() as session:
        rows = list_materials_with_price(session)
    st.dataframe(pd.DataFrame([{
        "ID": r.id, "Матеріал": r.name, "Од.": r.unit, "Ціна, грн": r.price,
        "Діє з": r.valid_from, "Джерело": r.source,
    } for r in rows]), hide_index=True, width="stretch")
    label_by_id = {f"{r.name} ({r.unit})": r.id for r in rows}

    c1, c2 = st.columns(2)
    with c1.form("update_price"):
        st.markdown("**Нова ціна матеріалу**")
        label = st.selectbox("Матеріал", list(label_by_id))
        value = st.number_input("Ціна за одиницю, грн", min_value=0.0, step=1.0)
        valid_from = st.date_input("Діє з", value=date.today())
        source = st.text_input("Джерело", value="manual")
        if st.form_submit_button("Зберегти ціну"):
            with Session() as session:
                saved(update_price(session, label_by_id[label], value, valid_from, source))
    with c2.form("add_material", clear_on_submit=True):
        st.markdown("**Новий матеріал**")
        name = st.text_input("Назва")
        unit = st.selectbox("Одиниця", UNITS)
        if st.form_submit_button("Додати"):
            try:
                with Session() as session:
                    add_material(session, name, unit)
                st.success(f"Додано: {name}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    hist_label = st.selectbox("Історія цін", list(label_by_id), key="history")
    with Session() as session:
        history = price_history(session, label_by_id[hist_label])
    st.dataframe(pd.DataFrame([{"Діє з": p.valid_from, "Ціна, грн": p.value, "Джерело": p.source}
                               for p in history]), hide_index=True, width="stretch")


def labour_tab(Session) -> None:
    st.caption("Вартість роботи (праці) за 1 м² виду робіт, без матеріалів.")
    with Session() as session:
        rows = list_labour_rates(session)
    st.dataframe(pd.DataFrame([{
        "Код": r.code, "Робота": WORK_NAMES_UA.get(r.code, r.name), "Ціна за м², грн": r.price,
        "Діє з": r.valid_from, "Джерело": r.source,
    } for r in rows]), hide_index=True, width="stretch")
    names = {r.code: WORK_NAMES_UA.get(r.code, r.name) for r in rows}

    with st.form("update_labour"):
        st.markdown("**Нова розцінка**")
        code = st.selectbox("Робота", list(names), format_func=names.get)
        value = st.number_input("Ціна за м², грн", min_value=0.0, step=1.0)
        valid_from = st.date_input("Діє з", value=date.today())
        source = st.text_input("Джерело", value="manual")
        if st.form_submit_button("Зберегти розцінку"):
            with Session() as session:
                saved(update_labour_rate(session, code, value, valid_from, source))

    hist_code = st.selectbox("Історія розцінок", list(names), format_func=names.get, key="labour_history")
    with Session() as session:
        history = labour_history(session, hist_code)
    st.dataframe(pd.DataFrame([{"Діє з": r.valid_from, "Ціна за м², грн": r.value, "Джерело": r.source}
                               for r in history]), hide_index=True, width="stretch")


def main() -> None:
    check_access()
    Session = get_sessionmaker()
    st.title("Ціни і матеріали")
    st.caption("Ціни не перезаписуються: нова ціна додається з датою, стара лишається в історії, "
               "тож попередні звіти можна відтворити.")
    t1, t2 = st.tabs(["Матеріали", "Розцінки на роботи"])
    with t1:
        materials_tab(Session)
    with t2:
        labour_tab(Session)


main()
