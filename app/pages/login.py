import streamlit as st

from app import common
from db import repo
from db.seed import DEMO_EMAIL, DEMO_PASSWORD

left, mid, right = st.columns([1, 2, 1])
with mid:
    st.title(":material/solar_power: Asistent Prosumator")
    st.markdown("Înțelegeți-vă factura de energie, verificați-o cu datele invertorului și aflați cât veți "
                "produce și consuma în zilele următoare.")

    if st.button("Intră în contul demo", type="primary", icon=":material/play_arrow:", width="stretch"):
        u = repo.authenticate(DEMO_EMAIL, DEMO_PASSWORD)
        if u:
            common.login(u)
            st.rerun()
        st.error("Contul demo nu este disponibil încă. Reîncărcați pagina peste câteva secunde.")
    st.caption("Gospodărie fictivă din București: 6 kWp, baterie 5 kWh, un an de date de la invertor.")

    tab_in, tab_new = st.tabs(["Autentificare", "Cont nou"])
    with tab_in:
        with st.form("login"):
            email = st.text_input("E-mail")
            password = st.text_input("Parolă", type="password")
            if st.form_submit_button("Intră", width="stretch"):
                u = repo.authenticate(email, password)
                if u:
                    common.login(u)
                    st.rerun()
                st.error("E-mail sau parolă greșită.")
    with tab_new:
        with st.form("signup"):
            email = st.text_input("E-mail", key="su_email")
            password = st.text_input("Parolă (minim 8 caractere)", type="password", key="su_pw")
            agree = st.checkbox("Sunt de acord ca datele încărcate (facturi, exporturi) să fie folosite doar "
                                "pentru calculele din aplicație.")
            if st.form_submit_button("Creează cont", width="stretch"):
                if "@" not in email or "." not in email.split("@")[-1]:
                    st.error("Adresa de e-mail nu pare validă.")
                elif len(password) < 8:
                    st.error("Parola trebuie să aibă cel puțin 8 caractere.")
                elif not agree:
                    st.error("Bifați acordul pentru a continua.")
                elif repo.get_user_by_email(email):
                    st.error("Există deja un cont cu acest e-mail.")
                else:
                    common.login(repo.create_user(email, password))
                    st.rerun()
    st.caption("Prototip pentru AI Validation Bootcamp, Challenge 1. Plățile rulează în modul de test Stripe: "
               "nu se percep bani reali.")
