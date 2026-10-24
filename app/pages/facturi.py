from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from app import common
from bills import suppliers
from bills.check import check_bill
from bills.complaint import draft
from bills.parse import parse_bill
from bills.validate import apply_confidence, validate
from db import repo
from engine.pipeline import all_rules
from rules.compensation import rule_for
from rules.explain import LINE_LABELS, energy_balance, explain_line, why_pay_note

user = common.user()
site = common.require_site()
LABEL_TO_TYPE = {v: k for k, v in LINE_LABELS.items()}

st.title("Facturi")


def _lines_frame(lines: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Tip": LINE_LABELS.get(ln["line_type"], LINE_LABELS["other"]),
        "Text pe factură": ln.get("label_raw") or "",
        "kWh": ln.get("qty_kwh"),
        "Preț (lei/kWh)": ln.get("unit_price"),
        "Valoare (lei)": ln.get("amount_lei"),
        "Verificați": (ln.get("confidence") or 0) < 0.8,
    } for ln in lines], columns=["Tip", "Text pe factură", "kWh", "Preț (lei/kWh)", "Valoare (lei)", "Verificați"])


def _frame_to_lines(df: pd.DataFrame, original: list[dict]) -> list[dict]:
    out = []
    for i, row in df.reset_index(drop=True).iterrows():
        def val(col, row=row):
            v = row[col]
            return None if pd.isna(v) else float(v)
        before = original[i] if i < len(original) else {}
        out.append({
            "line_type": LABEL_TO_TYPE.get(row["Tip"], "other"), "label_raw": row["Text pe factură"] or "",
            "qty_kwh": val("kWh"), "unit_price": val("Preț (lei/kWh)"), "amount_lei": val("Valoare (lei)"),
            "confidence": before.get("confidence", 1.0), "user_confirmed": True,
        })
    return out


def render_bill(bill: dict, ctx: str) -> None:
    rule = rule_for(bill["period_end"] or date.today(), site.get("customer_type") or "individual",
                    site["kwp"], all_rules())
    bal = energy_balance(bill["lines"])
    st.markdown(f"#### {bal['sentence']}")
    note = why_pay_note(bill["lines"])
    if note:
        st.info(note, icon=":material/help:")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Consumat din rețea", common.kwh(bal["consumed"]) if bal["consumed"] is not None else "–")
    m2.metric("Livrat în rețea", common.kwh(bal["delivered"]) if bal["delivered"] is not None else "–")
    m3.metric("Compensat", common.kwh(bal["compensated"]) if bal["compensated"] is not None else "–")
    m4.metric("Total de plată", common.lei(bill.get("total_lei")) if bill.get("total_lei") is not None else "–")

    st.markdown("##### Ce înseamnă fiecare rând")
    for ln in bill["lines"]:
        label = LINE_LABELS.get(ln["line_type"], ln.get("label_raw"))
        value = common.lei(ln["amount_lei"]) if ln.get("amount_lei") is not None else (
            common.kwh(ln["qty_kwh"]) if ln.get("qty_kwh") is not None else "")
        with st.expander(f"{label} · {value}"):
            st.write(explain_line(ln, rule, bill.get("vat_rate")))
            if ln.get("label_raw"):
                st.caption(f"Pe factură: „{ln['label_raw']}”")
    if rule:
        st.caption(f"Explicațiile folosesc regula: {rule.label}." + ("" if rule.verified else " Detaliile regulii sunt încă în curs de verificare."))

    st.markdown("##### Verificare cu datele invertorului")
    if not common.is_premium(user):
        st.info("Comparăm energia de pe factură cu ce a măsurat invertorul și recalculăm compensarea. "
                "Disponibil în Premium.", icon=":material/lock:")
        st.page_link("pages/abonament.py", label="Vezi abonamentul", icon=":material/workspace_premium:")
        return
    checks = repo.get_checks(bill["id"])
    c1, c2 = st.columns([1, 1])
    threshold = c1.slider("Prag de semnalare (%)", 2, 30, 10, key=f"{ctx}_thr_{bill['id']}",
                          help="Diferențele mai mari decât pragul sunt marcate „merită verificat”.")
    carried = c2.number_input("Credit reportat din luna anterioară (kWh, opțional)", min_value=0.0, value=None,
                              key=f"{ctx}_carry_{bill['id']}", help="De pe factura lunii anterioare, rândul „Cantitate reportată”.")
    if st.button("Verifică factura", icon=":material/fact_check:", key=f"{ctx}_chk_{bill['id']}") or not checks:
        readings = repo.load_readings(site["id"])
        checks = check_bill(bill, readings, rule, carried, site["kwp"], float(threshold))
        repo.save_checks(bill["id"], checks)
    for c in checks:
        common.show_check(c)

    flagged = [c for c in checks if c.get("severity") == "worth_checking"]
    if flagged:
        st.markdown("##### Cerere de verificare către furnizor")
        d = draft(bill, checks, site, user["email"])
        text = st.text_area("Revizuiți și completați textul, apoi trimiteți-l dumneavoastră furnizorului.",
                            d["body"], height=360, key=f"{ctx}_complaint_{bill['id']}")
        st.download_button("Descarcă textul (.txt)", text.encode("utf-8"), file_name=f"cerere_verificare_{bill['id']}.txt",
                           icon=":material/download:", key=f"{ctx}_dl_{bill['id']}")


tab_up, tab_hist = st.tabs(["Încarcă o factură", "Istoric"])

with tab_up:
    st.write("Încărcați factura ca PDF sau fotografiați-o cu telefonul. Fișierul nu este păstrat: "
             "salvăm doar valorile citite, după ce le confirmați.")
    up = st.file_uploader("Factura (PDF, JPG, PNG)", type=["pdf", "jpg", "jpeg", "png"], key="bill_upload")
    with st.expander("Nu aveți o factură la îndemână?"):
        st.write("Folosiți factura demonstrativă (furnizor fictiv), făcută pentru contul demo.")
        try:
            with open(common.repo_path("data/demo/factura_demo_2026-09.pdf"), "rb") as f:
                st.download_button("Descarcă factura demo (PDF)", f.read(), "factura_demo_2026-09.pdf",
                                   icon=":material/download:")
            with open(common.repo_path("data/demo/factura_demo_2026-09_poza.jpg"), "rb") as f:
                st.download_button("Descarcă factura demo ca poză (JPG)", f.read(), "factura_demo_2026-09_poza.jpg",
                                   icon=":material/photo_camera:")
        except FileNotFoundError:
            st.caption("Fișierele demo lipsesc (rulați scripts/make_demo_bill.py).")

    if up is not None:
        file_key = f"{up.name}:{up.size}"
        if st.session_state.get("draft_key") != file_key:
            with st.spinner("Citim factura..."):
                try:
                    st.session_state["draft"] = parse_bill(up.getvalue(), up.name)
                    st.session_state["draft_key"] = file_key
                    st.session_state.pop("saved_bill_id", None)
                except Exception as exc:  # noqa: BLE001 - show the reason, keep the page alive
                    st.error(f"Nu am putut citi factura: {exc}")
                    st.session_state.pop("draft", None)

    draft_bill = st.session_state.get("draft")
    if draft_bill and not st.session_state.get("saved_bill_id"):
        method = "text din PDF" if draft_bill["parse_method"] == "pdf_text" else f"OCR (încredere {draft_bill['ocr_confidence']:.0f}%)"
        st.success(f"Am citit {len(draft_bill['lines'])} rânduri, prin {method}. Încredere generală: "
                   f"{draft_bill['confidence']:.0%}.", icon=":material/document_scanner:")
        for w in draft_bill["warnings"]:
            st.warning(w)
        for c in draft_bill["validation"]:
            (st.success if c["ok"] else st.error)(c["message"], icon=":material/calculate:")

        with st.form("confirm_bill"):
            st.markdown("**Verificați valorile citite.** Rândurile marcate „Verificați” au încredere scăzută.")
            names = suppliers.names()
            sup = draft_bill.get("supplier") or site.get("supplier")
            c1, c2, c3 = st.columns(3)
            supplier = c1.selectbox("Furnizor", names, index=names.index(sup) if sup in names else len(names) - 1)
            p_start = c2.date_input("Început perioadă", value=draft_bill.get("period_start"), format="DD.MM.YYYY")
            p_end = c3.date_input("Sfârșit perioadă", value=draft_bill.get("period_end"), format="DD.MM.YYYY")
            c4, c5, c6 = st.columns(3)
            pod = c4.text_input("Cod loc de consum (POD)", value=draft_bill.get("pod") or "")
            vat_rate = c5.number_input("Cota TVA (%)", value=float(draft_bill.get("vat_rate") or 21.0), step=1.0)
            total = c6.number_input("Total de plată (lei)", value=draft_bill.get("total_lei"), step=0.01, format="%.2f")
            edited = st.data_editor(
                _lines_frame(draft_bill["lines"]), num_rows="dynamic", width="stretch", hide_index=True,
                column_config={
                    "Tip": st.column_config.SelectboxColumn(options=list(LINE_LABELS.values()), required=True),
                    "kWh": st.column_config.NumberColumn(format="%.0f"),
                    "Preț (lei/kWh)": st.column_config.NumberColumn(format="%.4f"),
                    "Valoare (lei)": st.column_config.NumberColumn(format="%.2f"),
                    "Verificați": st.column_config.CheckboxColumn(disabled=True),
                })
            if st.form_submit_button("Confirmă și salvează", type="primary", icon=":material/check:"):
                lines = _frame_to_lines(edited, draft_bill["lines"])
                fields = {"lines": lines, "vat_rate": vat_rate, "index_old": draft_bill.get("index_old"),
                          "index_new": draft_bill.get("index_new"), "field_confidence": draft_bill.get("field_confidence", {})}
                conf = apply_confidence(fields, validate(fields))
                bill_id = repo.save_bill(site["id"], {
                    "supplier": supplier if supplier != "Alt furnizor" else None,
                    "period_start": p_start, "period_end": p_end, "pod": pod or None,
                    "total_lei": total, "vat_rate": vat_rate, "parse_method": draft_bill["parse_method"],
                    "confidence": conf, "status": "confirmed", "file_path": None,
                }, lines)
                st.session_state["saved_bill_id"] = bill_id
                st.rerun()
        with st.expander("Textul citit de pe factură"):
            st.code(draft_bill["raw_text"][:6000], language=None)

    if st.session_state.get("saved_bill_id"):
        bill = repo.get_bill(st.session_state["saved_bill_id"])
        if bill:
            st.success("Factura a fost salvată.", icon=":material/check_circle:")
            render_bill(bill, "new")

with tab_hist:
    bills = [b for b in repo.list_bills(site["id"]) if b["status"] == "confirmed"]
    if not bills:
        st.write("Nicio factură salvată încă.")
    else:
        rows = []
        for b in bills:
            full = repo.get_bill(b["id"])
            bal = energy_balance(full["lines"])
            rows.append({"id": b["id"], "Perioada": f"{b['period_start']:%m.%Y}" if b["period_start"] else "?",
                         "Furnizor": b.get("supplier") or "", "Consumat (kWh)": bal["consumed"],
                         "Livrat (kWh)": bal["delivered"], "Compensat (kWh)": bal["compensated"],
                         "Total (lei)": b.get("total_lei"), "start": b["period_start"]})
        hist = pd.DataFrame(rows)
        if common.is_premium(user) and len(hist) > 1:
            chart_df = hist.dropna(subset=["start"]).sort_values("start")
            st.altair_chart(alt.Chart(chart_df).mark_bar(color="#2f6db5").encode(
                x=alt.X("Perioada:N", sort=list(chart_df["Perioada"]), title=None),
                y=alt.Y("Total (lei):Q"), tooltip=["Perioada", "Total (lei)", "Consumat (kWh)", "Livrat (kWh)"],
            ).properties(height=220), width="stretch")
        elif not common.is_premium(user):
            st.caption("Evoluția lunară a facturilor este în Premium.")
        st.dataframe(hist.drop(columns=["id", "start"]), hide_index=True, width="stretch")
        labels = {f"{r['Perioada']} · {r['Furnizor']} · {common.lei(r['Total (lei)'])}": r["id"] for r in rows}
        pick = st.selectbox("Deschide factura", list(labels))
        bill = repo.get_bill(labels[pick])
        render_bill(bill, "hist")
        if st.button("Șterge această factură", icon=":material/delete:", key=f"del_{bill['id']}"):
            repo.delete_bill(bill["id"])
            st.rerun()
