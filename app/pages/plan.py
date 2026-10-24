import altair as alt
import pandas as pd
import streamlit as st

from app import common
from db import repo
from engine import plan_service
from engine.devices import CATALOG, KINDS
from engine.planner import settings_with_defaults
from engine.profiles import AREAS, USAGE_TYPES

user = common.user()
site = common.require_site()
settings = settings_with_defaults(repo.get_plan_settings(site["id"]))
has_panels = float(site.get("kwp") or 0) > 0

st.title("Plan sistem")
st.write("Câte panouri și baterii vă trebuie ca să folosiți acasă aproape toată energia produsă, stocând surplusul, "
         "astfel încât să cumpărați și să vindeți cât mai puțin din rețea." +
         ("" if has_panels else " Nu aveți încă panouri: planul pornește de la zero."))


def save_settings(changes: dict) -> None:
    repo.save_plan_settings(site["id"], {**repo.get_plan_settings(site["id"]), **changes})
    st.rerun()


# ---------------------------------------------------------------- inputs
with st.expander("1. Consumul casei", expanded=False):
    with st.form("baseline"):
        mode = st.radio("Consumul de bază", ["auto", "devices"], horizontal=True,
                        index=0 if settings["baseline_mode"] != "devices" else 1,
                        format_func={"auto": "Din datele mele (sau profilul distribuitorului)",
                                     "devices": "Doar din lista de aparate"}.get)
        c1, c2, c3 = st.columns(3)
        annual = c1.number_input("Consum anual (kWh, opțional)", min_value=0.0, value=float(settings["annual_kwh"] or 0),
                                 step=100.0, help="Folosit dacă nu avem cel puțin două săptămâni de date de la invertor.")
        area = c2.radio("Zona", list(AREAS), format_func=AREAS.get, horizontal=True,
                        index=list(AREAS).index(settings["area"]))
        usage_opts = ["auto"] + list(USAGE_TYPES)
        usage = c3.selectbox("Când consumați", usage_opts, index=usage_opts.index(settings["usage_type"]),
                             format_func=lambda k: "Automat (din datele mele, altfel profil mediu)" if k == "auto" else USAGE_TYPES[k])
        if st.form_submit_button("Salvează"):
            save_settings({"baseline_mode": mode, "annual_kwh": annual or None, "area": area, "usage_type": usage})

with st.expander("2. Aparate (consum nou sau toate aparatele)", expanded=True):
    st.caption("Adăugați aparatele pe care le veți cumpăra (marcate „Nou”), sau toate aparatele casei dacă alegeți "
               "consumul „doar din lista de aparate”. Valorile tipice sunt orientative: modificați-le după etichetă.")
    devices = repo.list_devices(site["id"])
    c1, c2 = st.columns([3, 1])
    pick = c1.selectbox("Adaugă din catalog", [c["key"] for c in CATALOG],
                        format_func=lambda k: next(c["name"] for c in CATALOG if c["key"] == k))
    if c2.button("Adaugă", icon=":material/add:", width="stretch"):
        tpl = {k: v for k, v in next(c for c in CATALOG if c["key"] == pick).items() if k != "key"}
        repo.save_device(site["id"], {"is_new": settings["baseline_mode"] != "devices", **tpl})
        st.rerun()
    if devices:
        cols = ["id", "name", "kind", "quantity", "power_w", "hours_per_day", "start_hour", "days_per_week",
                "annual_kwh", "ev_km_day", "ev_kwh_100km", "flexible", "is_new"]
        df = pd.DataFrame(devices)[cols]
        edited = st.data_editor(
            df, hide_index=True, width="stretch", num_rows="dynamic", key="dev_editor",
            column_config={
                "id": None,
                "name": st.column_config.TextColumn("Aparat", required=True),
                "kind": st.column_config.SelectboxColumn("Tip", options=list(KINDS), required=True),
                "quantity": st.column_config.NumberColumn("Buc.", min_value=1, step=1),
                "power_w": st.column_config.NumberColumn("Putere (W)", min_value=0),
                "hours_per_day": st.column_config.NumberColumn("Ore/zi", min_value=0.0, max_value=24.0),
                "start_hour": st.column_config.NumberColumn("Pornește la", min_value=0, max_value=23, step=1),
                "days_per_week": st.column_config.NumberColumn("Zile/săpt.", min_value=0, max_value=7, step=1),
                "annual_kwh": st.column_config.NumberColumn("kWh/an (încălzire, răcire)", min_value=0.0),
                "ev_km_day": st.column_config.NumberColumn("km/zi (mașină)", min_value=0.0),
                "ev_kwh_100km": st.column_config.NumberColumn("kWh/100 km", min_value=0.0),
                "flexible": st.column_config.CheckboxColumn("Pot muta ora"),
                "is_new": st.column_config.CheckboxColumn("Nou"),
            })
        if st.button("Salvează aparatele", icon=":material/save:"):
            keep = set()
            for row in edited.to_dict(orient="records"):
                row = {k: (None if pd.isna(v) else v) for k, v in row.items()}
                if not row.get("name") or not row.get("kind"):
                    continue
                dev_id = int(row.pop("id")) if row.get("id") else None
                months = next((d["months"] for d in devices if d["id"] == dev_id), list(range(1, 13)))
                saved = repo.save_device(site["id"], {**row, "months": months,
                                                      "flexible": bool(row.get("flexible")), "is_new": row.get("is_new") is not False}, dev_id)
                keep.add(saved["id"])
            for d in devices:
                if d["id"] not in keep:
                    repo.delete_device(site["id"], d["id"])
            st.rerun()
        st.caption("Tipuri: " + " · ".join(f"**{k}**: {v}" for k, v in KINDS.items()))
    else:
        st.write("Niciun aparat adăugat.")

with st.expander("3. Panouri, baterii și prețuri"):
    with st.form("system"):
        c1, c2, c3, c4 = st.columns(4)
        panel_wp = c1.number_input("Putere panou (W)", 200, 800, int(settings["panel_wp"]), 5)
        module = c2.number_input("Modul baterie (kWh)", 1.0, 20.0, float(settings["battery_module_kwh"]), 0.5)
        max_panels = c3.number_input("Maxim panouri (acoperiș)", 0, 200, int(settings["max_panels"]))
        max_modules = c4.number_input("Maxim module baterie", 0, 20, int(settings["max_battery_modules"]))
        c1, c2, c3, c4 = st.columns(4)
        min_cycles = c1.number_input("Cicluri minime / an pentru o baterie", 0, 365, int(settings["min_cycles"]),
                                     help="O baterie care s-ar încărca complet de mai puțin de atâtea ori pe an stă nefolosită.")
        p_pv = c2.number_input("Preț montat (lei/kWp)", 0.0, 20000.0, float(settings["price_pv_lei_kwp"]), 100.0)
        p_bat = c3.number_input("Preț baterie (lei/kWh)", 0.0, 10000.0, float(settings["price_batt_lei_kwh"]), 50.0)
        p_inst = c4.number_input("Montaj baterie (lei)", 0.0, 20000.0, float(settings["batt_install_lei"]), 100.0)
        c1, c2, c3, c4 = st.columns(4)
        h_retro = c1.number_input("Invertor hibrid, schimbare (lei)", 0.0, 30000.0, float(settings["hybrid_retrofit_lei"]), 100.0)
        h_new = c2.number_input("Invertor hibrid, sistem nou (lei în plus)", 0.0, 30000.0, float(settings["hybrid_new_lei"]), 100.0)
        has_hybrid = c3.checkbox("Am deja invertor hibrid", value=bool(settings["has_hybrid_inverter"]))
        subsidy = c4.number_input("Alte subvenții (lei)", 0.0, 100000.0, float(settings["subsidy_lei"] or 0), 500.0)
        c1, c2, c3, c4 = st.columns(4)
        casa_verde = c1.checkbox("Includ Casa Verde Baterii (≥10 kWh)", value=bool(settings["casa_verde_baterii"]),
                                 help="75% din cost, maxim 15.000 lei, plafon 1.500 lei/kWh (OUG 1904/2026). "
                                      "Sesiunea AFM nu era anunțată la 13.10.2026.")
        share = c2.slider("După 2030, surplusul valorează (% din preț)", 0, 100, int(100 * settings["post2030_export_share"]))
        esc = c3.number_input("Creștere anuală preț energie (%)", -5.0, 20.0, float(settings["price_escalation_pct"]), 0.5)
        ex_cost = c4.number_input("Cât a costat sistemul actual (lei)", 0.0, 500000.0, float(settings["existing_cost_lei"] or 0), 500.0,
                                  disabled=not has_panels)
        ex_year = st.number_input("Anul instalării sistemului actual", 2010, 2030, int(settings["existing_year"] or 2024),
                                  disabled=not has_panels)
        st.caption("Prețuri implicite (cu TVA), verificate de sursele lor la 13.10.2026: sisteme montate ~2.900–5.000 lei/kWp, "
                   "baterii ~720–2.300 lei/kWh plus montaj 1.500–3.000 lei, invertor hibrid la schimbare 4.500–7.000 lei. "
                   "Înlocuiți-le cu oferta instalatorului.")
        if st.form_submit_button("Salvează"):
            save_settings({"panel_wp": panel_wp, "battery_module_kwh": module, "max_panels": max_panels,
                           "max_battery_modules": max_modules, "min_cycles": min_cycles, "price_pv_lei_kwp": p_pv,
                           "price_batt_lei_kwh": p_bat, "batt_install_lei": p_inst, "hybrid_retrofit_lei": h_retro,
                           "hybrid_new_lei": h_new, "has_hybrid_inverter": has_hybrid, "subsidy_lei": subsidy,
                           "casa_verde_baterii": casa_verde, "post2030_export_share": share / 100,
                           "price_escalation_pct": esc, "existing_cost_lei": ex_cost or None,
                           "existing_year": ex_year if ex_cost else None})
    if st.button("Revino la valorile implicite"):
        repo.save_plan_settings(site["id"], {k: v for k, v in repo.get_plan_settings(site["id"]).items()
                                             if k in ("baseline_mode", "annual_kwh", "area", "usage_type")})
        st.rerun()

# ---------------------------------------------------------------- result
force = st.button("Recalculează planul", icon=":material/refresh:")
with st.spinner("Simulăm un an întreg pentru fiecare combinație de panouri și baterii..."):
    p = plan_service.plan_for_site(repo.get_site(site["id"]), force=force)
rec, cur, base = p["recommended"], p["current"], p["baseline"]
wp, mod = rec["panel_wp"], rec["battery_module_kwh"]

st.divider()
if has_panels:
    if rec["panels_added"] or rec["battery_modules_added"]:
        parts = []
        if rec["panels_added"]:
            parts.append(f"**{rec['panels_added']} {'panou' if rec['panels_added'] == 1 else 'panouri'}** de {wp} W")
        if rec["battery_modules_added"]:
            n = rec["battery_modules_added"]
            parts.append(f"**{n} {'modul' if n == 1 else 'module'} de baterie** de {common.num(mod, 1)} kWh")
        head = (f"Adăugați {' și '.join(parts)}. Total: {common.num(rec['kwp'], 2)} kWp și "
                f"{common.num(rec['battery_kwh'], 1)} kWh stocare.")
    else:
        head = "Sistemul actual este deja cel mai eficient pentru consumul dumneavoastră: nu adăugați nimic."
else:
    head = (f"Recomandare: **{rec['panels_total']} panouri** de {wp} W ({common.num(rec['kwp'], 2)} kWp) și "
            f"**{rec['battery_modules_total']} module de baterie** de {common.num(mod, 1)} kWh "
            f"({common.num(rec['battery_kwh'], 1)} kWh), invertor de ~{common.num(rec['inverter_kw_suggested'], 1)} kW.")
st.subheader("Recomandarea")
st.markdown(f"#### {head}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Cumpărat din rețea / an", common.kwh(rec["bought_kwh"]), delta=common.kwh(rec["bought_kwh"] - cur["bought_kwh"]), delta_color="inverse")
c2.metric("Vândut în rețea / an", common.kwh(rec["sold_kwh"]), delta=common.kwh(rec["sold_kwh"] - cur["sold_kwh"]), delta_color="inverse")
c3.metric("Energie solară folosită acasă", f"{common.num(rec['self_consumption_pct'], 0)}%",
          help="Din tot ce produc panourile, cât folosiți direct sau din baterie.")
c4.metric("Consum acoperit de panouri", f"{common.num(rec['self_sufficiency_pct'], 0)}%")
st.caption(f"Consum anual luat în calcul: {common.kwh(p['demand_kwh'])} · producție {common.kwh(p['production']['kwh_per_kwp_year'])} "
           f"pe kWp · {p['production']['weather_source']} · {p['combinations_tested']} combinații testate.")

alt_df = pd.DataFrame(p["alternatives"]).rename(columns={
    "label": "Variantă", "kwp": "kWp", "battery_kwh": "Baterie (kWh)", "bought_kwh": "Cumpărat (kWh/an)",
    "sold_kwh": "Vândut (kWh/an)", "exchange_kwh": "Cumpărat + vândut", "self_sufficiency_pct": "Acoperire (%)",
    "battery_cycles": "Cicluri/an (toată bateria)"}).drop(columns=["panels_added", "modules_added"])
st.dataframe(alt_df, hide_index=True, width="stretch")
for r in p["stop_reasons"]:
    st.caption(f"• {r}")

months = pd.DataFrame(p["months_current"]).assign(v="Acum").pipe(
    lambda a: pd.concat([a, pd.DataFrame(p["months_recommended"]).assign(v="Cu planul")]))
months["Luna"] = months["month"].str[5:7] + "." + months["month"].str[2:4]
order = list(dict.fromkeys(months["Luna"]))
c1, c2 = st.columns(2)
for col, field, title, colors in ((c1, "bought", "Cumpărat din rețea (kWh/lună)", ["#c0504d", "#e8a0a0"]),
                                   (c2, "sold", "Vândut în rețea (kWh/lună)", ["#7cb342", "#c5e1a5"])):
    col.altair_chart(alt.Chart(months).mark_bar().encode(
        x=alt.X("Luna:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("v:N", sort=["Acum", "Cu planul"]),
        y=alt.Y(f"{field}:Q", title=None),
        color=alt.Color("v:N", sort=["Acum", "Cu planul"], scale=alt.Scale(range=[colors[1], colors[0]]), title=None,
                        legend=alt.Legend(orient="top")),
        tooltip=["Luna", "v", alt.Tooltip(f"{field}:Q", format=".0f")],
    ).properties(title=title, height=230), width="stretch")
st.caption("Iarna se cumpără mai mult (soare puțin), vara se vinde surplusul de la prânz. Bateriile mută energia de la zi "
           "la seară, nu de la vară la iarnă.")

if p["schedule_tips"]:
    st.subheader("Mutați aparatele flexibile la soare")
    for t in p["schedule_tips"]:
        st.success(f"**{t['name']}**: mutați pornirea la ora {t['to_hour']}:00 (acum {t['from_hour']}:00). "
                   f"Ar folosi {common.kwh(t['solar_kwh_after'])} pe an din panouri în loc de {common.kwh(t['solar_kwh_now'])}.",
                   icon=":material/schedule:")

st.subheader("Bani și amortizare")
money, costs = p["payback"], p["costs"]
if money is None:
    st.info("Adăugați în Profil prețul pe kWh din contract ca să calculăm amortizarea.")
    st.page_link("pages/profil.py", label="Profil", icon=":material/edit:")
elif costs["gross_lei"] == 0:
    st.write("Nu este nimic de cumpărat, deci nimic de amortizat.")
else:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Investiție", common.lei(costs["gross_lei"]))
    c2.metric("Subvenții", common.lei(costs["subsidy_lei"]))
    c3.metric("De plătit", common.lei(costs["net_lei"]))
    c4.metric("Economie în primul an", common.lei(money["scenarios"]["current"]["saving_year1_lei"]))
    st.caption(f"Panouri {common.lei(costs['panels_lei'])} · baterie {common.lei(costs['battery_lei'])} · invertor "
               f"{common.lei(costs['inverter_lei'])}. Factura de energie pe un an: {common.lei(money['bills_year1']['before_lei'])} → "
               f"{common.lei(money['bills_year1']['after_lei'])}." +
               (f" Bateria se înlocuiește în anul {money['battery_replacement_year']} (inclus)." if money["battery_replacement_year"] else ""))
    rows, lines = [], []
    for sc in money["scenarios"].values():
        rows.append({"Scenariu după 2030": sc["label"],
                     "Amortizare": f"{common.num(sc['payback_years'], 1)} ani" if sc["payback_years"] is not None else "peste 25 de ani",
                     "Economie / an după 2030": common.lei(sc["saving_after_2030_lei"])})
        lines += [{"An": money["start_year"] + i, "lei": v, "Scenariu": sc["label"]} for i, v in enumerate(sc["cumulative_lei"])]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    ldf = pd.DataFrame(lines)
    chart = alt.Chart(ldf).mark_line(strokeWidth=2).encode(
        x=alt.X("An:O", title=None), y=alt.Y("lei:Q", title="Economii cumulate (lei)"),
        color=alt.Color("Scenariu:N", legend=alt.Legend(orient="bottom", columns=1), title=None),
        tooltip=["An", "Scenariu", alt.Tooltip("lei:Q", format=",.0f")])
    rule = alt.Chart(pd.DataFrame({"lei": [costs["net_lei"]]})).mark_rule(strokeDash=[5, 4], color="#555").encode(y="lei:Q")
    st.altair_chart((chart + rule).properties(height=300), width="stretch")
    st.caption("Linia punctată: suma de plătit. Până în 2030 se aplică regulile de azi; după, cele trei scenarii sunt ipoteze, "
               "nu prognoze. Calculul acoperă doar energia: tarifele fixe nu se schimbă.")
if p.get("existing_payback"):
    e = p["existing_payback"]
    pb = e["payback_years"]["current"]
    st.info(f"Sistemul actual ({common.lei(e['cost_lei'])}, instalat în {e['installed']}) economisește ~{common.lei(e['saving_year_lei'])} "
            f"pe an la consumul de azi" + (f" și se amortizează în ~{common.num(pb, 1)} ani." if pb else "."), icon=":material/savings:")

st.subheader("De știut")
st.markdown(f"**Consumul de bază:** {base['label']} · {common.kwh(base['annual_kwh'])}/an · încredere {base['confidence']}.")
for n in base["notes"]:
    st.caption(f"• {n}")
for lim in p["limits"]:
    st.caption(f"• {lim}")
