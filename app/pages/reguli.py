from datetime import date

import pandas as pd
import streamlit as st
import yaml

from alerts import ntfy
from alerts.rules_publish import publish, simulate_for_user
from app import common
from db import repo
from engine.pipeline import all_rules
from rules.compensation import CUSTOMER_TYPES, STAGED_DIR, Rule, load_rule_file, previous_rule, rule_for
from rules.explain import change_note

user = common.user()
site = common.require_site()
ctype, kw = site.get("customer_type") or "individual", float(site["kwp"])
rules = all_rules()

st.title("Reguli & alerte")
current = rule_for(date.today(), ctype, kw, rules)

st.subheader("Regula care se aplică acum pentru dumneavoastră")
if current is None:
    st.warning(f"Nicio regulă de compensare cantitativă nu se aplică unei instalații de {kw:g} kW "
               f"({CUSTOMER_TYPES.get(ctype, ctype).lower()}).")
else:
    st.markdown(f"**{current.title}**  \nÎn vigoare din {current.effective_from:%d.%m.%Y} · versiunea {current.version}")
    st.write(current.summary_ro)
    p = current.params
    facts = {
        "Tip compensare": "cantitativă (kWh pentru kWh)" if p.get("compensation_type") == "quantity" else p.get("compensation_type"),
        "Calcul": "lunar" if p.get("netting_period") == "month" else p.get("netting_period"),
        "Limită putere": f"{p.get('quantity_compensation_max_kw')} kW",
        "Disponibilă până la": str(p.get("quantity_compensation_until")),
        "Valabilitate surplus reportat": f"{p['carryover_months']} luni" if p.get("carryover_months") else "neverificată",
        "Tarife de rețea pe energia compensată": "neverificat" if p.get("network_tariffs_on_compensated") is None
        else ("da" if p["network_tariffs_on_compensated"] else "nu"),
    }
    st.dataframe(pd.DataFrame(facts.items(), columns=["", "Valoare"]), hide_index=True, width="stretch")
    src = current.source + (f" ([link]({current.source_url}))" if current.source_url else "")
    st.caption(f"Sursa: {src}." + ("" if current.verified else " Neverificat încă cu textul legii și metodologia ANRE."))

    st.subheader("Ce s-a schimbat pentru mine")
    old = previous_rule(current, ctype, kw, rules)
    note = change_note(old, current, ctype, kw)
    for line in note["changes"]:
        st.markdown(f"- {line}")
    st.info(note["impact"], icon=":material/person:")

with st.expander("Toate versiunile regulilor"):
    st.dataframe(pd.DataFrame([{"Versiune": r.version, "În vigoare din": r.effective_from.strftime("%d.%m.%Y"),
                                "Titlu": r.title, "Verificat": "da" if r.verified else "nu"} for r in rules]),
                 hide_index=True, width="stretch")

st.subheader("Alerte pe telefon")
topic = user.get("ntfy_topic")
st.markdown(f"""Primiți o notificare când se schimbă regulile, cu ce înseamnă pentru instalația dumneavoastră:
1. Instalați aplicația **ntfy** din Google Play (gratuită, fără cont).
2. Apăsați **+**, scrieți subiectul **`{topic}`** și apăsați *Subscribe*.
3. Apăsați butonul de mai jos ca să verificați că funcționează.""")
st.caption(f"Sau deschideți {ntfy.subscribe_url(topic)} în browser. Subiectul este privat: nu îl împărțiți.")
c1, c2 = st.columns(2)
if c1.button("Trimite o notificare de test", icon=":material/notifications_active:", width="stretch"):
    ok = ntfy.send(topic, "Asistent Prosumator", "Notificările funcționează. Vă anunțăm când se schimbă regulile.",
                   tags=["white_check_mark"])
    (st.success if ok else st.error)("Trimisă. Verificați telefonul." if ok else "Nu am putut trimite notificarea (ntfy indisponibil).")

demo_path = STAGED_DIR / "demo_next_version.yaml"
if demo_path.exists() and c2.button("Simulează o schimbare de lege (DEMO)", icon=":material/science:",
                                    width="stretch",
                                    help="Trimite doar către dumneavoastră nota personalizată pentru o regulă inventată. "
                                         "Nu schimbă regulile folosite în calcule."):
    res = simulate_for_user(load_rule_file(demo_path), user, site)
    (st.success if res["delivered"] else st.warning)(
        "Notificare trimisă pe telefon." if res["delivered"] else "Salvată în aplicație (ntfy indisponibil).")
    st.text(res["message"])

st.subheader("Istoric alerte")
notes = repo.list_notifications(user["id"], limit=20)
if not notes:
    st.write("Nicio alertă încă.")
for n in notes:
    p = n["payload_json"] or {}
    with st.container(border=True):
        sent = f"{n['sent_at']:%d.%m.%Y %H:%M}" if n.get("sent_at") else ""
        st.markdown(f"**{p.get('title', n['type'])}** · {sent} · "
                    f"{'trimisă pe telefon' if n['delivered'] else 'doar în aplicație'}")
        st.text(p.get("message", ""))

if user.get("is_admin"):
    st.divider()
    st.subheader("Administrare: publică o versiune nouă")
    st.caption("Calea obișnuită: adăugați un fișier YAML în rules/versions/ și faceți push; GitHub Actions trimite "
               "notificările. Aici puteți publica direct, pentru toți utilizatorii.")
    up = st.file_uploader("Fișier YAML cu noua versiune", type=["yaml", "yml"])
    if up is not None:
        try:
            rule = Rule.from_dict(yaml.safe_load(up.getvalue().decode("utf-8")))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Fișier invalid: {exc}")
            st.stop()
        st.json(rule.to_dict(), expanded=False)
        if rule.demo:
            st.warning("Aceasta este o regulă DEMO: nu o publicați pentru toți utilizatorii.")
        elif st.button("Publică și notifică utilizatorii", type="primary", icon=":material/campaign:"):
            res = publish(rule)
            st.success(f"Publicată: {'nouă' if res['new'] else 'actualizată'}; {len(res['notified'])} utilizatori notificați.")
