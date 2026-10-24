"""Plain-Romanian explanations for bill lines and rule changes. Templates only: nothing is guessed."""
from __future__ import annotations

from rules.compensation import CUSTOMER_TYPES, Rule, is_number

LINE_LABELS = {
    "energy_consumed": "Energie activă consumată",
    "energy_delivered": "Energie activă livrată (produsă)",
    "energy_compensated": "Energie compensată",
    "carryover": "Cantitate reportată",
    "energy_billed": "Energie activă facturată",
    "distribution_tariff": "Tarif de distribuție",
    "transport_tariff": "Tarif de transport",
    "system_services": "Servicii de sistem",
    "green_certificates": "Certificate verzi",
    "cogeneration": "Contribuție cogenerare",
    "excise": "Acciză",
    "subtotal": "Total fără TVA",
    "vat": "TVA",
    "total": "Total de plată",
    "other": "Altă linie",
}

ENERGY_TYPES = {"energy_consumed", "energy_delivered", "energy_compensated", "carryover"}
MONEY_TYPES = {"energy_billed", "distribution_tariff", "transport_tariff", "system_services",
               "green_certificates", "cogeneration", "excise", "other"}


def _n(x, digits: int = 2) -> str:
    """Romanian number format: 1.234,56"""
    if not is_number(x):
        return "?"
    s = f"{float(x):,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def kwh(x) -> str:
    return f"{_n(x, 0)} kWh"


def lei(x) -> str:
    return f"{_n(x, 2)} lei"


def explain_line(line: dict, rule: Rule | None = None, vat_rate: float | None = None) -> str:
    t = line.get("line_type", "other")
    q, a, p = line.get("qty_kwh"), line.get("amount_lei"), line.get("unit_price")
    rule_ref = f" Regula folosită: {rule.label}." if rule else ""
    on_kwh = f" Se aplică pe {kwh(q)}." if is_number(q) else ""

    if t == "energy_consumed":
        return (f"Energia pe care ați luat-o din rețea în această perioadă: {kwh(q)}. "
                "O măsoară contorul distribuitorului, nu invertorul dumneavoastră.")
    if t == "energy_delivered":
        return f"Energia produsă de panouri pe care ați trimis-o în rețea: {kwh(q)}."
    if t == "energy_compensated":
        return (f"Din energia consumată, {kwh(q)} au fost acoperiți de energia livrată: compensare "
                f"cantitativă, kWh pentru kWh, calculată lunar.{rule_ref}")
    if t == "carryover":
        return (f"Surplusul de {kwh(q)} livrați și nefolosiți trece în luna următoare și va acoperi "
                "consumul viitor.")
    if t == "energy_billed":
        price = f" × {_n(p, 4)} lei/kWh" if is_number(p) else ""
        qty = kwh(q) if is_number(q) else "energia rămasă"
        return f"Energia rămasă de plată după compensare: {qty}{price} = {lei(a)}."
    if t == "distribution_tariff":
        return f"Plătește rețeaua locală care aduce curentul până la casa dumneavoastră: {lei(a)}.{on_kwh}"
    if t == "transport_tariff":
        return f"Plătește rețeaua națională de înaltă tensiune (Transelectrica): {lei(a)}.{on_kwh}"
    if t == "system_services":
        return f"Acoperă echilibrarea și siguranța sistemului energetic național: {lei(a)}.{on_kwh}"
    if t == "green_certificates":
        return f"Contribuție obligatorie prin care consumatorii susțin producția de energie verde: {lei(a)}."
    if t == "cogeneration":
        return f"Contribuție stabilită de stat pentru centralele de cogenerare de înaltă eficiență: {lei(a)}."
    if t == "excise":
        return f"Acciza este un impozit al statului pe energia electrică consumată: {lei(a)}."
    if t == "subtotal":
        return f"Suma tuturor liniilor de mai sus, înainte de TVA: {lei(a)}."
    if t == "vat":
        rate = f" de {_n(vat_rate, 0)}%" if is_number(vat_rate) else ""
        return f"TVA{rate} se adaugă peste toate celelalte sume: {lei(a)}."
    if t == "total":
        return f"Suma pe care o aveți de plătit pentru această factură: {lei(a)}."
    return (f"Linie pe care nu am recunoscut-o automat („{line.get('label_raw', '')}”). "
            "Verificați-o pe factură sau întrebați furnizorul.")


def energy_balance(lines: list[dict]) -> dict:
    def total(t):
        vals = [ln.get("qty_kwh") for ln in lines if ln.get("line_type") == t and is_number(ln.get("qty_kwh"))]
        return sum(vals) if vals else None

    consumed, delivered = total("energy_consumed"), total("energy_delivered")
    compensated, carry = total("energy_compensated"), total("carryover")
    billed = total("energy_billed")
    if billed is None and consumed is not None and compensated is not None:
        billed = max(0.0, consumed - compensated)
    parts = []
    if consumed is not None:
        parts.append(f"ați folosit {kwh(consumed)} din rețea")
    if delivered is not None:
        parts.append(f"ați trimis {kwh(delivered)}")
    if compensated is not None:
        parts.append(f"{kwh(compensated)} au fost compensați")
    if billed is not None:
        parts.append(f"plătiți energia pentru {kwh(billed)}")
    sentence = ("Pe scurt: " + ", ".join(parts) + ".") if parts else ""
    if carry:
        sentence += f" Rămân {kwh(carry)} credit pentru lunile următoare."
    return {"consumed": consumed, "delivered": delivered, "compensated": compensated,
            "billed": billed, "carryover": carry, "sentence": sentence}


def why_pay_note(lines: list[dict]) -> str | None:
    """The most common confusion: energy fully compensated, but the bill is not zero."""
    bal = energy_balance(lines)
    total = next((ln.get("amount_lei") for ln in lines if ln.get("line_type") == "total"), None)
    if bal["billed"] is not None and bal["billed"] < 0.5 and is_number(total) and total > 0:
        return ("Energia consumată a fost compensată integral, dar factura nu este zero: tarifele de rețea, "
                "contribuțiile, acciza și TVA se plătesc separat de energie.")
    return None


# ---------------------------------------------------------------- rule changes
def _eligibility(rule: Rule | None, customer_type: str, kw: float) -> str:
    if rule is None:
        return "nicio regulă"
    max_kw = rule.params.get("quantity_compensation_max_kw")
    ok = rule.params.get("compensation_type") == "quantity" and (max_kw is None or kw <= max_kw)
    return "compensare cantitativă" if ok else "fără compensare cantitativă"


def diff_rules(old: Rule | None, new: Rule) -> list[str]:
    if old is None:
        return ["Prima regulă înregistrată pentru profilul dumneavoastră."]
    o, n = old.params, new.params
    changes = []
    if o.get("quantity_compensation_max_kw") != n.get("quantity_compensation_max_kw"):
        changes.append(f"Limita pentru compensare cantitativă: {o.get('quantity_compensation_max_kw')} kW → "
                       f"{n.get('quantity_compensation_max_kw')} kW.")
    if o.get("netting_period") != n.get("netting_period"):
        changes.append(f"Perioada de calcul: {o.get('netting_period')} → {n.get('netting_period')}.")
    if str(o.get("quantity_compensation_until")) != str(n.get("quantity_compensation_until")):
        changes.append(f"Compensarea cantitativă este disponibilă până la {n.get('quantity_compensation_until')}.")
    if (o.get("financial_settlement") or None) != (n.get("financial_settlement") or None):
        fs = n.get("financial_settlement")
        if fs:
            plural = {"individual": "persoanele fizice", "company": "companiile",
                      "public_institution": "instituțiile publice"}
            types = " și ".join(plural.get(t, t) for t in fs.get("customer_types", []))
            changes.append(f"Nou: {types} cu instalații între {fs.get('min_kw')} și {fs.get('max_kw')} kW pot cere "
                           f"regularizare financiară ({fs.get('price_basis')}).")
        else:
            changes.append("Regularizarea financiară nu mai este disponibilă.")
    if o.get("carryover_months") != n.get("carryover_months"):
        changes.append(f"Valabilitatea surplusului reportat: {o.get('carryover_months') or 'nespecificată'} → "
                       f"{n.get('carryover_months') or 'nespecificată'} luni.")
    return changes or ["Modificări de detaliu, fără efect asupra parametrilor de compensare."]


def change_note(old: Rule | None, new: Rule, customer_type: str, kw: float) -> dict:
    """Personalised note for one user. Returns title + message (Romanian)."""
    prefix = "[DEMO] " if new.demo else ""
    before, after = _eligibility(old, customer_type, kw), _eligibility(new, customer_type, kw)
    lines = diff_rules(old, new)
    if before == after:
        impact = (f"Pentru instalația dumneavoastră de {kw:g} kWp ({CUSTOMER_TYPES.get(customer_type, customer_type).lower()}) "
                  f"nu se schimbă tipul de compensare: rămâneți la {after}.")
    else:
        impact = f"Pentru instalația dumneavoastră de {kw:g} kWp: {before} → {after}."
    fs = new.params.get("financial_settlement") or {}
    if fs and customer_type in fs.get("customer_types", []) and fs.get("min_kw", 0) <= kw <= fs.get("max_kw", 0):
        impact += " Puteți alege regularizarea financiară; verificați ce variantă vă avantajează."
    message = (f"{new.title}, în vigoare din {new.effective_from:%d.%m.%Y}.\n"
               + "\n".join(f"• {ln}" for ln in lines) + f"\n{impact}")
    if not new.verified:
        message += "\nDetaliile sunt încă în curs de verificare cu textul legii și metodologia ANRE."
    return {"title": f"{prefix}S-a schimbat legea: ce înseamnă pentru dumneavoastră", "message": message,
            "impact": impact, "changes": lines}
