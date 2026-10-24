import pandas as pd
import streamlit as st

from app import common
from db import repo
from engine import pvgis

user = common.user()
site = common.require_site()

st.title("Prognoză")
common.require_premium("Prognoza de producție, consum și factură")

top = st.columns([3, 1])
force = top[1].button("Recalculează", icon=":material/refresh:", width="stretch")
fc = common.forecast(site, force=force)
top[0].caption(f"Vreme: {fc['weather_source']} · model: {fc['model_version']} · consum: {fc['load_method']}")

hourly, daily, month = fc["hourly"], fc["daily"], fc["month"]

st.subheader("Producție și consum, pe ore")
st.altair_chart(common.hourly_chart(hourly), width="stretch")
legend = "Linia portocalie: producția estimată. Linia albastră punctată: consumul estimat."
if hourly["pv_p10"].notna().any():
    legend += (" Banda: percentilele 10–90 ale modelului pentru vremea prognozată; nu include "
                   "greșelile prognozei meteo, deci în realitate intervalul este mai larg.")
else:
    legend += " Banda de incertitudine apare după ce antrenați modelul pe datele invertorului."
st.caption(legend + " " + fc["lead_note"])

st.subheader("Pe zile")
st.altair_chart(common.daily_bars(daily, {"pv": "Producție", "load": "Consum", "exported": "Export",
                                          "imported": "Import"}), width="stretch")
table = daily.rename(columns={"pv": "Producție", "load": "Consum", "self_consumed": "Autoconsum",
                              "exported": "Export", "imported": "Import"}).round(1)
table.index = [common.day_label(ts) for ts in table.index]
st.dataframe(table, width="stretch")

st.subheader(f"Factura estimată pentru {common.month_name(month['month_start'])}")
if month["est_lei"] is not None:
    st.markdown(f"#### Aproximativ {common.kwh(month['billed_kwh'])} facturați după compensare, "
                f"adică circa **{common.lei(month['est_lei'])}** pentru energie.")
else:
    st.markdown(f"#### Aproximativ {common.kwh(month['billed_kwh'])} facturați după compensare.")
    st.page_link("pages/profil.py", label="Adăugați prețul din contract (lei/kWh) ca să vedeți suma în lei",
                 icon=":material/edit:")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Consum din rețea", common.kwh(month["consumed_kwh"]))
c2.metric("Livrat în rețea", common.kwh(month["delivered_kwh"]))
c3.metric("Compensat", common.kwh(month["compensated_kwh"]))
c4.metric("Credit reportat la final", common.kwh(month["new_carryover_kwh"]))
st.caption(f"Din {month['measured_days']:g} zile măsurate, {month['forecast_days']:g} zile prognozate și "
           f"{month['extrapolated_days']:g} zile extrapolate. Suma acoperă doar energia: tarifele de rețea, "
           "contribuțiile și TVA se adaugă separat, ca pe factură.")
for n in month["notes"]:
    st.caption(f"• {n}")

st.subheader("Cât de precisă este prognoza pentru sistemul dumneavoastră")
sm, lm = fc.get("solar_metrics"), fc.get("load_metrics")
if sm:
    acc = pd.DataFrame([
        {"Metodă": "Model fizic + corecție învățată", "Eroare medie (kWh/oră)": sm.get("mae_kwh_corrected"),
         "Eroare (% din kWp)": sm.get("nmae_pct_corrected")},
        {"Metodă": "Doar model fizic", "Eroare medie (kWh/oră)": sm.get("mae_kwh_physics"),
         "Eroare (% din kWp)": sm.get("nmae_pct_physics")},
        {"Metodă": "„Aceeași oră de ieri”", "Eroare medie (kWh/oră)": sm.get("mae_kwh_persistence"),
         "Eroare (% din kWp)": sm.get("nmae_pct_persistence")},
    ])
    st.dataframe(acc, hide_index=True, width="stretch")
    st.caption(f"Testat pe datele de după {sm.get('test_from')} ({sm.get('hours_scored')} ore cu soare), neatinse la "
               "antrenare, cu vremea reală. Cu prognoza meteo eroarea este mai mare, mai ales după ziua 2.")
else:
    st.write("Încărcați un export de la invertor și antrenați modelul ca să vedeți precizia pentru acoperișul dumneavoastră.")
    st.page_link("pages/date_invertor.py", label="Date invertor", icon=":material/upload_file:")
if lm:
    st.caption(f"Consum: eroare medie {common.num(lm.get('mae_kwh_model'), 3)} kWh/oră, față de "
               f"{common.num(lm.get('mae_kwh_baseline'), 3)} kWh/oră pentru media ultimelor 4 săptămâni.")

if site.get("pvgis_monthly_json"):
    readings = repo.load_readings(site["id"])
    if not readings.empty:
        cmp = pvgis.compare(readings["pv_kwh"], site["pvgis_monthly_json"])
        if cmp and cmp["message"]:
            st.subheader("Comparație cu PVGIS")
            (st.warning if cmp["ratio"] and (cmp["ratio"] < 0.8 or cmp["ratio"] > 1.2) else st.info)(
                f"{cmp['message']} ({cmp['months']} luni: real {common.kwh(cmp['actual_kwh'])}, "
                f"PVGIS {common.kwh(cmp['expected_kwh'])}, raport {common.num(cmp['ratio'] * 100)}%).")

csv = hourly.copy()
csv.index = csv.index.tz_convert("Europe/Bucharest")
st.download_button("Descarcă prognoza orară (CSV)", csv.round(3).to_csv(sep=";", decimal=",").encode("utf-8"),
                   "prognoza.csv", icon=":material/download:")
