import streamlit as st

from app import common
from db import repo
from rules.explain import energy_balance, why_pay_note

user = common.user()
site = common.require_site()

st.title("Acasă")
st.caption(f"{site['kwp']:g} kWp · înclinare {site['tilt']:g}° · orientare {site['azimuth']:g}° · "
           f"baterie {site.get('battery_kwh') or 0:g} kWh · {site.get('supplier') or 'furnizor nesetat'}")

fc = common.forecast(site)
daily = fc["daily"].iloc[1:] if len(fc["daily"]) > 7 else fc["daily"]   # first day is partial (from now)
month = fc["month"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Producție estimată, 7 zile", common.kwh(daily["pv"].sum()))
if common.is_premium(user):
    c2.metric("Consum estimat, 7 zile", common.kwh(daily["load"].sum()))
    c3.metric(f"Factura pe {common.month_name(month['month_start'])}",
              common.lei(month["est_lei"]) if month["est_lei"] is not None else common.kwh(month["billed_kwh"]),
              help="Energia rămasă de plată după compensare, înmulțită cu prețul din contract. Fără tarife fixe.")
    c4.metric("Credit reportat estimat", common.kwh(month["new_carryover_kwh"]))
else:
    c2.metric("Consum estimat, 7 zile", "Premium")
    c3.metric("Factura lunii (estimare)", "Premium")
    c4.metric("Credit reportat", "Premium")

if not float(site.get("kwp") or 0):
    st.info("Nu aveți încă panouri. Aflați câte panouri și baterii vi se potrivesc în pagina Plan sistem.",
            icon=":material/calculate:")
    st.page_link("pages/plan.py", label="Plan sistem", icon=":material/calculate:")
st.subheader("Următoarele 7 zile")
cols = {"pv": "Producție", "load": "Consum"} if common.is_premium(user) else {"pv": "Producție"}
st.altair_chart(common.daily_bars(daily, cols), width="stretch")
st.caption(f"Vreme: {fc['weather_source']}. {fc['lead_note']}")
if not common.is_premium(user):
    st.page_link("pages/prognoza.py", label="Prognoza pe ore, consumul și factura estimată sunt în Premium",
                 icon=":material/lock:")

left, right = st.columns(2)
with left:
    st.subheader("Ultima factură")
    bills = [b for b in repo.list_bills(site["id"]) if b["status"] == "confirmed"]
    if not bills:
        st.write("Nu ați încărcat încă nicio factură.")
        st.page_link("pages/facturi.py", label="Încarcă o factură (PDF sau poză)", icon=":material/upload:")
    else:
        b = repo.get_bill(bills[0]["id"])
        period = (f"{b['period_start']:%d.%m.%Y} – {b['period_end']:%d.%m.%Y}" if b["period_start"] else "perioadă necunoscută")
        st.markdown(f"**{b.get('supplier') or 'Furnizor'}**, {period}: **{common.lei(b['total_lei'])}**")
        st.write(energy_balance(b["lines"])["sentence"])
        note = why_pay_note(b["lines"])
        if note:
            st.info(note, icon=":material/help:")
        flagged = [c for c in repo.get_checks(b["id"]) if c["severity"] == "worth_checking"]
        if flagged:
            st.warning(f"{len(flagged)} diferență(e) de verificat față de invertor.", icon=":material/warning:")
        st.page_link("pages/facturi.py", label="Detalii factură", icon=":material/receipt_long:")

with right:
    st.subheader("Alerte")
    notes = repo.list_notifications(user["id"], limit=3)
    if not notes:
        st.write("Nicio alertă. Vă anunțăm pe telefon când se schimbă regulile pentru prosumatori.")
    for n in notes:
        p = n["payload_json"] or {}
        with st.container(border=True):
            st.markdown(f"**{p.get('title', n['type'])}**")
            st.caption(f"{n['sent_at']:%d.%m.%Y %H:%M}" if n.get("sent_at") else "")
            st.write(p.get("impact") or p.get("message", "")[:300])
    st.page_link("pages/reguli.py", label="Reguli & alerte", icon=":material/gavel:")

summary = repo.readings_summary(site["id"])
if summary["rows"]:
    st.caption(f"Date invertor: {summary['rows']:,} ore, {summary['start'].tz_convert(common.LOCAL_TZ):%d.%m.%Y} – {summary['end'].tz_convert(common.LOCAL_TZ):%d.%m.%Y}."
               .replace(",", "."))
else:
    st.caption("Nu ați încărcat încă date de la invertor. Prognoza folosește doar modelul fizic.")
    st.page_link("pages/date_invertor.py", label="Încarcă exportul din aplicația invertorului", icon=":material/upload_file:")
