"""Entry point: streamlit run app/Home.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app import common  # noqa: E402
from db import repo  # noqa: E402

st.set_page_config(page_title="Asistent Prosumator", page_icon=":material/solar_power:", layout="wide")
common.secrets_to_env()
boot = common.bootstrap()

# Returning from Stripe Checkout: a fresh browser session, restore the login from the signed token
token = st.query_params.get("u")
if token and not st.session_state.get("user_id"):
    uid = common.verify_login(token)
    if uid and repo.get_user(uid):
        st.session_state["user_id"] = uid
if token:
    del st.query_params["u"]          # don't leave a login token in the address bar

user = common.user()
if user is None:
    nav = st.navigation([st.Page("pages/login.py", title="Autentificare", icon=":material/login:",
                                 url_path="login", default=True)], position="hidden")
    nav.run()
    st.stop()

site = repo.get_site_for_user(user["id"])
pages = {
    "": [
        st.Page("pages/acasa.py", title="Acasă", icon=":material/home:", url_path="acasa", default=site is not None),
        st.Page("pages/facturi.py", title="Facturi", icon=":material/receipt_long:", url_path="facturi"),
        st.Page("pages/prognoza.py", title="Prognoză", icon=":material/wb_sunny:", url_path="prognoza"),
        st.Page("pages/date_invertor.py", title="Date invertor", icon=":material/upload_file:", url_path="date"),
        st.Page("pages/reguli.py", title="Reguli & alerte", icon=":material/gavel:", url_path="reguli"),
    ],
    "Cont": [
        st.Page("pages/abonament.py", title="Abonament", icon=":material/workspace_premium:", url_path="abonament"),
        st.Page("pages/profil.py", title="Profil", icon=":material/solar_power:", url_path="profil", default=site is None),
    ],
}

with st.sidebar:
    st.markdown("### :material/solar_power: Asistent Prosumator")
    plan = "Premium" if common.is_premium(user) else "Gratuit"
    st.caption(f"{user['email']} · plan {plan}")
    if st.button("Ieșire", icon=":material/logout:", width="stretch"):
        common.logout()
        st.rerun()
    if boot.get("status") == "error":
        st.caption(f"Contul demo nu a putut fi pregătit: {boot.get('error')}")
    st.caption("Prototip · AI Validation Bootcamp 2026. Datele contului demo sunt fictive.")

st.navigation(pages).run()
