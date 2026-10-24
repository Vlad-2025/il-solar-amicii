import pandas as pd
import streamlit as st

from app import common
from db import repo
from engine.pipeline import train_models
from ingest.detect import ENERGY_ROLES, ROLES, guess_mapping, read_table
from ingest.normalize import normalize

user = common.user()
site = common.require_site()

st.title("Date invertor")
st.write("Încărcați exportul din aplicația invertorului (CSV, Excel sau JSON). Îl transformăm în valori orare "
         "și antrenăm prognoza pe acoperișul dumneavoastră.")

summary = repo.readings_summary(site["id"])
if summary["rows"]:
    c1, c2, c3 = st.columns(3)
    c1.metric("Ore cu date", f"{summary['rows']:,}".replace(",", "."))
    c2.metric("De la", f"{summary['start'].tz_convert(common.LOCAL_TZ):%d.%m.%Y}")
    c3.metric("Până la", f"{summary['end'].tz_convert(common.LOCAL_TZ):%d.%m.%Y}")
    if not summary["has_load"]:
        st.info("Exportul nu conține consumul casei (necesită contor la racordul la rețea). Pentru prognoza "
                "consumului folosim un profil tipic scalat la consumul lunar din profil.", icon=":material/info:")

up = st.file_uploader("Export invertor", type=["csv", "txt", "xlsx", "xls", "json"])
with st.expander("Nu aveți un export? Descărcați exportul demo"):
    path = common.repo_path("data/demo/demo_inverter_export.csv")
    if path.exists():
        st.download_button("Descarcă exportul demo (CSV)", path.read_bytes(), "demo_inverter_export.csv",
                           icon=":material/download:")
    else:
        st.caption("Fișierul demo lipsește (rulați scripts/make_demo_data.py).")

if up is not None:
    try:
        raw = read_table(up.getvalue(), up.name)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Nu am putut citi fișierul: {exc}")
        st.stop()
    guess = guess_mapping(raw)
    if guess["format"]:
        st.success(f"Format recunoscut: {guess['format']}.", icon=":material/check_circle:")
    else:
        st.info("Format necunoscut: am ghicit coloanele după nume. Verificați-le mai jos.", icon=":material/tune:")
    st.dataframe(raw.head(8), width="stretch", hide_index=True)

    with st.form("mapping"):
        st.markdown("**Ce conține fiecare coloană**")
        options = ["—"] + list(raw.columns)
        mapping, units, kinds = {}, {}, {}
        ts_col = st.selectbox(ROLES["timestamp"], options,
                              index=options.index(guess["mapping"]["timestamp"]) if guess["mapping"].get("timestamp") in options else 0)
        for role in ENERGY_ROLES + ["soc"]:
            c1, c2, c3 = st.columns([3, 1, 1])
            cur = guess["mapping"].get(role)
            col = c1.selectbox(ROLES[role], options, index=options.index(cur) if cur in options else 0, key=f"map_{role}")
            unit_opts = ["%"] if role == "soc" else ["kWh", "Wh", "kW", "W"]
            gu = guess["units"].get(role, unit_opts[0])
            unit = c2.selectbox("Unitate", unit_opts, index=unit_opts.index(gu) if gu in unit_opts else 0, key=f"unit_{role}")
            gk = guess["kind"].get(role) if isinstance(guess["kind"], dict) else guess["kind"]
            cumulative = c3.checkbox("Contor cumulativ", value=gk == "cumulative", key=f"cum_{role}",
                                     disabled=role == "soc", help="Valoarea crește continuu (index), nu energia pe interval.")
            if col != "—":
                mapping[role] = col
                units[role] = unit
                kinds[role] = "cumulative" if cumulative else "interval"
        c1, c2, c3 = st.columns(3)
        label = c1.radio("Ora din fișier marchează", ["începutul intervalului", "sfârșitul intervalului"],
                         index=0 if guess["label"] == "start" else 1)
        tz = c2.text_input("Fus orar al fișierului", value=guess["timezone"])
        dayfirst = c3.checkbox("Data începe cu ziua (31.12.2026)", value=guess.get("dayfirst", True))
        submitted = st.form_submit_button("Importă datele", type="primary", icon=":material/upload:")

    if submitted:
        if ts_col == "—":
            st.error("Alegeți coloana cu data și ora.")
            st.stop()
        mapping["timestamp"] = ts_col
        try:
            hourly, rep = normalize(raw, mapping, units, kinds, "start" if label.startswith("înc") else "end",
                                    tz, dayfirst, kwp=site["kwp"])
        except Exception as exc:  # noqa: BLE001
            st.error(f"Import eșuat: {exc}")
            st.stop()
        n = repo.save_readings(site["id"], hourly)
        common._forecast_cached.clear()
        st.success(f"Am importat {n:,} ore ({rep['start'].tz_convert(common.LOCAL_TZ):%d.%m.%Y} – {rep['end'].tz_convert(common.LOCAL_TZ):%d.%m.%Y}), interval original "
                   f"{rep['interval_minutes']} min.".replace(",", "."), icon=":material/check_circle:")
        details = {"Rânduri în fișier": rep["rows_in"], "Duplicate eliminate": rep["duplicates_removed"],
                   "Ore lipsă": rep["gap_hours"], "Rânduri pierdute la schimbarea orei": rep["dst_rows_dropped"]}
        st.dataframe(pd.DataFrame([details]), hide_index=True)
        st.dataframe(pd.DataFrame([rep["totals_kwh"]]).rename(columns={
            "pv_kwh": "Producție (kWh)", "load_kwh": "Consum (kWh)", "grid_import_kwh": "Import (kWh)",
            "grid_export_kwh": "Export (kWh)", "batt_charge_kwh": "Încărcare (kWh)",
            "batt_discharge_kwh": "Descărcare (kWh)"}), hide_index=True)
        for w in rep["warnings"]:
            st.warning(w)
        st.session_state["needs_training"] = True

st.divider()
st.subheader("Modelele de prognoză")
solar_m, load_m = repo.load_model(site["id"], "solar"), repo.load_model(site["id"], "load")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**Producție (corecție învățată)**")
    if solar_m:
        m = solar_m["metrics_json"] or {}
        st.write(f"Antrenat pe {m.get('data_from')} – {m.get('data_to')}. Eroare medie: "
                 f"{common.num(m.get('nmae_pct_corrected'), 2)}% din kWp (doar fizică: {common.num(m.get('nmae_pct_physics'), 2)}%, "
                 f"„ca ieri”: {common.num(m.get('nmae_pct_persistence'), 2)}%).")
    else:
        st.write("Neantrenat: prognoza folosește doar modelul fizic.")
with c2:
    st.markdown("**Consum**")
    if load_m:
        m = load_m["metrics_json"] or {}
        st.write(f"Eroare medie {common.num(m.get('mae_kwh_model'), 3)} kWh/oră "
                 f"(media ultimelor 4 săptămâni: {common.num(m.get('mae_kwh_baseline'), 3)} kWh/oră).")
    else:
        st.write("Neantrenat: folosim un profil tipic scalat la consumul lunar.")

if summary["rows"] or st.session_state.get("needs_training"):
    if st.button("Antrenează modelele pe datele mele", icon=":material/model_training:",
                 type="primary" if st.session_state.get("needs_training") else "secondary"):
        with st.spinner("Descărcăm vremea istorică și antrenăm modelele (până la un minut)..."):
            report = train_models(repo.get_site(site["id"]))
        st.session_state["needs_training"] = False
        for kind, label in (("solar", "Producție"), ("load", "Consum")):
            r = report.get(kind, {})
            if "error" in r:
                st.warning(f"{label}: {r['error']}")
            else:
                st.success(f"{label}: model antrenat.", icon=":material/check_circle:")
        common.forecast(repo.get_site(site["id"]), force=True)
        st.rerun()

with st.expander("Șterge datele mele de la invertor"):
    st.write("Șterge toate valorile orare și modelele antrenate pentru această instalație.")
    if st.button("Șterge definitiv", icon=":material/delete_forever:"):
        repo.delete_readings(site["id"])
        repo.delete_models(site["id"])
        common.forecast(site, force=True)
        st.rerun()
