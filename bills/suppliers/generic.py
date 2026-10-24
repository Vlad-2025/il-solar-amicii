"""Generic extractor: works line by line using the Romanian terms list. Used for unknown suppliers
and as the base every supplier template starts from."""
from __future__ import annotations

import re
from datetime import date, datetime

from bills import terms_ro as T

ENERGY = {"energy_consumed", "energy_delivered", "energy_compensated", "carryover"}


def _date(s: str | None) -> date | None:
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_line(raw: str, line_type: str) -> dict:
    p = T.plain(raw)
    work = re.sub(T.DATE, " ", p)                       # dates are not amounts
    work = re.sub(r"\d{1,2}(?:[.,]\d+)?\s*%", " ", work)  # nor are percentages
    qty_m = T.QTY_RE.search(work)
    price_m = T.PRICE_RE.search(work)
    qty = T.parse_ro_number(qty_m.group(1)) if qty_m else None
    price = T.parse_ro_number(price_m.group(1)) if price_m else None

    spans = [m.span(1) for m in (qty_m, price_m) if m]
    others = [m for m in T.NUM_RE.finditer(work) if not any(a <= m.start() < b for a, b in spans)]
    amount = None
    if others and not re.search(r"kwh\s*$", work.strip()):
        amount = T.parse_ro_number(others[-1].group(0))
    if line_type in ENERGY:
        amount = None if amount is None or qty is None else amount

    expected = qty is not None if line_type in ENERGY else amount is not None
    return {
        "line_type": line_type, "label_raw": raw.strip()[:200], "qty_kwh": qty, "unit_price": price,
        "amount_lei": amount, "confidence": 0.9 if expected else 0.45,
    }


def extract(text: str, plain_text: str | None = None) -> dict:
    plain_text = plain_text if plain_text is not None else T.plain(text)
    fields: dict = {"field_confidence": {}}

    m = T.PERIOD_RE.search(plain_text)
    fields["period_start"], fields["period_end"] = (_date(m.group(1)), _date(m.group(2))) if m else (None, None)
    fields["field_confidence"]["period"] = 0.95 if m else 0.0

    m = T.POD_RE.search(plain_text)
    fields["pod"] = m.group(1).upper() if m else None
    fields["field_confidence"]["pod"] = 0.9 if m else 0.0

    for key, rx in (("index_old", T.INDEX_OLD_RE), ("index_new", T.INDEX_NEW_RE)):
        m = rx.search(plain_text)
        fields[key] = T.parse_ro_number(m.group(1)) if m else None

    m = T.VAT_RATE_RE.search(plain_text)
    fields["vat_rate"] = T.parse_ro_number(m.group(1)) if m else None

    lines = []
    for raw in text.splitlines():
        p = T.plain(raw)
        if not p.strip():
            continue
        t = T.classify(p)
        if t is None:
            continue
        if t in ("vat",) and not T.NUM_RE.search(re.sub(r"\d{1,2}(?:[.,]\d+)?\s*%", " ", p)):
            continue                                    # "TVA 21%" header without an amount
        lines.append(parse_line(raw, t))
    fields["lines"] = lines

    total = next((ln["amount_lei"] for ln in reversed(lines) if ln["line_type"] == "total" and ln["amount_lei"] is not None), None)
    fields["total_lei"] = total
    fields["field_confidence"]["total"] = 0.9 if total is not None else 0.0
    return fields
