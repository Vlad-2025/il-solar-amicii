import pandas as pd
import streamlit as st

from app import common
from bills import suppliers
from db import repo
from engine import pvgis, weather
from engine.solar import Site
from rules.compensation import CUSTOMER_TYPES

user = common.user()
site = repo.get_site_for_user(user["id"]) or {}
new = not site

st.title("Profil instalație" if not new else "Bun venit! Descrieți instalația")
if st.session_state.get("flash"):
    st.success(st.session_state.pop("flash"), icon=":material/check_circle:")
if new:
    st.write("Avem nevoie de locație și de datele panourilor pentru prognoza de producție. "
             "Le găsiți în contractul cu instalatorul sau în aplicația invertorului.")

@st.cache_data(ttl=86400, show_spinner=False)
def geocode(query: str) -> list[dict]:
    return weather.geocode(query)


ORIENT = {"Sud (180°)": 180.0, "Sud-Est (135°)": 135.0, "Sud-Vest (225°)": 225.0, "Est (90°)": 90.0,
          "Vest (270°)": 270.0, "Est-Vest (două fețe; folosiți 180°)": 180.0}

st.subheader("Locație")
q = st.text_input("Căutați localitatea", placeholder="ex. Cluj-Napoca, Bragadiru, Pitești")
if q:
    results = geocode(q)
    if results:
        labels = [f"{r['name']}, {r.get('admin') or ''} ({r['lat']:.3f}, {r['lon']:.3f})" for r in results]
        pick = st.selectbox("Rezultate", labels)
        r = results[labels.index(pick)]
        st.session_state["geo"] = r
    else:
        st.caption("Niciun rezultat (sau serviciul de căutare nu răspunde). Introduceți coordonatele manual.")
geo = st.session_state.get("geo") or {}

c1, c2, c3 = st.columns(3)
lat = c1.number_input("Latitudine", value=float(geo.get("lat") or site.get("lat") or 44.4268), format="%.4f")
lon = c2.number_input("Longitudine", value=float(geo.get("lon") or site.get("lon") or 26.1025), format="%.4f")
elev = c3.number_input("Altitudine (m)", value=float(geo.get("elevation") or site.get("elevation") or 80.0), step=10.0)
st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=10, height=220)
st.caption("Pentru precizie maximă, copiați coordonatele casei din Google Maps (clic dreapta pe acoperiș).")

with st.form("site"):
    st.subheader("Panouri și baterie")
    c1, c2, c3 = st.columns(3)
    kwp = c1.number_input("Putere instalată (kWp)", min_value=0.0, max_value=400.0,
                          value=float(site["kwp"]) if site.get("kwp") is not None else 6.0, step=0.1,
                          help="0 dacă nu aveți încă panouri: folosiți pagina Plan ca să aflați câte vă trebuie.")
    tilt = c2.slider("Înclinare panouri (°)", 0, 90, int(site.get("tilt") or 30))
    cur_az = float(site.get("azimuth") or 180.0)
    orient_labels = list(ORIENT) + ["Altă valoare"]
    default_orient = next((k for k, v in ORIENT.items() if v == cur_az), "Altă valoare")
    orient = c3.selectbox("Orientare", orient_labels, index=orient_labels.index(default_orient))
    az_custom = c3.number_input("Azimut (°; 180 = sud)", 0.0, 360.0, cur_az, step=5.0,
                                disabled=orient != "Altă valoare")
    c4, c5, c6 = st.columns(3)
    inverter = c4.number_input("Putere invertor (kW)", min_value=0.0, value=float(site.get("inverter_kw") or kwp), step=0.5)
    battery = c5.number_input("Baterie (kWh, 0 dacă nu aveți)", min_value=0.0, value=float(site.get("battery_kwh") or 0.0), step=0.5)
    monthly = c6.number_input("Consum lunar tipic (kWh)", min_value=0.0, value=float(site.get("monthly_kwh") or 250.0),
                              step=10.0, help="De pe facturi. Folosit când exportul invertorului nu are consumul casei.")

    st.subheader("Contract")
    c1, c2, c3 = st.columns(3)
    names = suppliers.names()
    supplier = c1.selectbox("Furnizor", names, index=names.index(site["supplier"]) if site.get("supplier") in names else len(names) - 1)
    ctypes = list(CUSTOMER_TYPES)
    ctype = c2.selectbox("Tip client", ctypes, format_func=CUSTOMER_TYPES.get,
                         index=ctypes.index(site.get("customer_type") or "individual"))
    comp_opts = {"quantity": "Compensare cantitativă", "financial": "Regularizare financiară"}
    comp = c3.selectbox("Tip compensare", list(comp_opts), format_func=comp_opts.get,
                        index=list(comp_opts).index(site.get("compensation_type") or "quantity"))
    c4, c5 = st.columns(2)
    price = c4.number_input("Preț total pe kWh din contract (lei, cu taxe)", min_value=0.0, max_value=5.0,
                            value=float(site.get("price_lei_kwh") or 0.0), step=0.01, format="%.2f",
                            help="Folosit pentru factura estimată. Nu îl ghicim: îl găsiți pe factură sau în contract.")
    carry = c5.number_input("Credit reportat pe ultima factură (kWh)", min_value=0.0,
                            value=float(site.get("carryover_kwh") or 0.0), step=1.0)
    saved = st.form_submit_button("Salvează", type="primary", icon=":material/save:")

if saved:
    azimuth = az_custom if orient == "Altă valoare" else ORIENT[orient]
    fields = {"lat": lat, "lon": lon, "elevation": elev, "kwp": kwp, "tilt": float(tilt), "azimuth": azimuth,
              "inverter_kw": (inverter or None) if kwp > 0 else None, "battery_kwh": battery, "monthly_kwh": monthly or None,
              "supplier": supplier if supplier != "Alt furnizor" else None, "customer_type": ctype,
              "compensation_type": comp, "price_lei_kwh": price or None, "carryover_kwh": carry}
    if site.get("label"):
        fields["label"] = site["label"]
    changed_geometry = any(site.get(k) != fields[k] for k in ("lat", "lon", "kwp", "tilt", "azimuth"))
    saved_site = repo.upsert_site(user["id"], fields)
    if kwp > 0 and (changed_geometry or not site.get("pvgis_annual_kwh")):
        try:
            with st.spinner("Cerem estimarea anuală de la PVGIS..."):
                pv = pvgis.fetch(Site.from_row(saved_site))
            repo.update_site(saved_site["id"], pvgis_annual_kwh=pv["annual_kwh"], pvgis_monthly_json=pv["monthly_kwh"])
        except pvgis.PVGISUnavailable:
            st.caption("PVGIS nu răspunde acum; încercăm la următoarea salvare.")
    st.session_state.pop("geo", None)
    st.session_state["flash"] = "Profil salvat." + (" Mergeți la Acasă pentru prognoză." if new else "")
    st.rerun()

if site.get("pvgis_annual_kwh"):
    st.info(f"PVGIS estimează pentru această locație și aceste panouri **{common.kwh(site['pvgis_annual_kwh'])} pe an**.",
            icon=":material/insights:")

st.divider()
st.subheader("Cont")
st.write(f"E-mail: {user['email']}")
st.write(f"Subiect notificări ntfy: `{user.get('ntfy_topic')}`")
