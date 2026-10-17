"""Materials administration — a SEPARATE Streamlit page (epic 5.6).

This is an admin tool, not part of the user flow. Streamlit shows every file in
ui/pages/ as its own entry in the sidebar, so this page lives beside the main
user app (ui/app.py) but is clearly distinct.

Access: if the ADMIN_PASSWORD environment variable is set, the page asks for it.
If it is not set, the page runs in dev mode with a visible warning. For a real
deployment, set ADMIN_PASSWORD (or run the admin as a separate, non-public app).

Run:  streamlit run ui/app.py   (then open "Materials admin" in the sidebar)
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from core import config  # noqa: E402
from pricedb import (  # noqa: E402
    add_material, list_materials_with_price, open_db, price_history, update_price,
)

st.set_page_config(page_title="Materials admin", page_icon="🧱")


def check_access() -> bool:
    """Password gate. Dev mode (no password) if ADMIN_PASSWORD is unset."""
    expected = os.environ.get("ADMIN_PASSWORD")
    if not expected:
        st.warning("ADMIN_PASSWORD is not set — admin screen is unprotected (dev mode).")
        return True
    if st.session_state.get("admin_ok"):
        return True
    entered = st.text_input("Admin password", type="password")
    if entered and entered == expected:
        st.session_state["admin_ok"] = True
        return True
    if entered:
        st.error("Wrong password.")
    st.stop()


@st.cache_resource
def get_sessionmaker():
    return open_db(config.path("materials_db"))   # creates and seeds the DB on first use


def main() -> None:
    check_access()
    Session = get_sessionmaker()

    st.title("Materials administration")
    st.caption("Add materials and update prices. Price updates keep the full history.")

    with Session() as session:
        rows = list_materials_with_price(session)

    st.subheader("Materials")
    if rows:
        st.dataframe(pd.DataFrame([{
            "ID": r.id, "Material": r.name, "Unit": r.unit, "Price": r.price,
            "Currency": r.currency, "Valid from": r.valid_from, "Source": r.source,
        } for r in rows]), hide_index=True, width="stretch")
    else:
        st.info("No materials yet. Create the database with scripts/init_db.py.")

    st.subheader("Add material")
    with st.form("add_material", clear_on_submit=True):
        name = st.text_input("Name")
        unit = st.selectbox("Unit", ["kg", "l", "m2", "m", "pcs"])
        if st.form_submit_button("Add"):
            try:
                with Session() as session:
                    add_material(session, name, unit)
                st.success(f"Added {name!r}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    if not rows:
        return

    label_by_id = {f"{r.name} ({r.unit})": r.id for r in rows}

    st.subheader("Update price")
    with st.form("update_price"):
        label = st.selectbox("Material", list(label_by_id))
        value = st.number_input("Price", min_value=0.0, step=1.0)
        valid_from = st.date_input("Valid from", value=date.today())
        source = st.text_input("Source", value="manual")
        if st.form_submit_button("Save price"):
            with Session() as session:
                result = update_price(session, label_by_id[label], value, valid_from, source)
            st.info("Price unchanged — no new row.") if result is None else \
                st.success("Price saved; previous value kept in history.")
            st.rerun()

    st.subheader("Price history")
    hist_label = st.selectbox("Show history for", list(label_by_id), key="history")
    with Session() as session:
        history = price_history(session, label_by_id[hist_label])
    if history:
        st.table(pd.DataFrame([{
            "Valid from": p.valid_from, "Price": p.value,
            "Currency": p.currency, "Source": p.source,
        } for p in history]))
    else:
        st.info("No price recorded yet.")


main()
