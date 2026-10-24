"""Arithmetic checks on a parsed bill. Passing checks raise confidence; failing ones send the
fields to the user for confirmation."""
from __future__ import annotations

from rules.explain import MONEY_TYPES, lei


def _close(a: float, b: float, rel: float = 0.005, abs_: float = 0.05) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def _amount(lines, t):
    vals = [ln["amount_lei"] for ln in lines if ln["line_type"] == t and ln.get("amount_lei") is not None]
    return vals[-1] if vals else None


def _qty(lines, t):
    vals = [ln["qty_kwh"] for ln in lines if ln["line_type"] == t and ln.get("qty_kwh") is not None]
    return vals[0] if vals else None


def validate(fields: dict) -> list[dict]:
    lines = fields.get("lines", [])
    checks: list[dict] = []
    money = [ln["amount_lei"] for ln in lines if ln["line_type"] in MONEY_TYPES and ln.get("amount_lei") is not None]
    subtotal, vat, total = _amount(lines, "subtotal"), _amount(lines, "vat"), _amount(lines, "total")
    base = subtotal if subtotal is not None else (sum(money) if money else None)

    if subtotal is not None and money:
        ok = _close(sum(money), subtotal)
        checks.append({"name": "sum_lines", "ok": ok,
                       "message": f"Suma liniilor ({lei(sum(money))}) {'=' if ok else '≠'} total fără TVA ({lei(subtotal)})."})
    if vat is not None and fields.get("vat_rate") and base is not None:
        expected = base * fields["vat_rate"] / 100
        ok = _close(expected, vat, abs_=0.06)
        checks.append({"name": "vat", "ok": ok,
                       "message": f"TVA {fields['vat_rate']:g}% din {lei(base)} = {lei(expected)}; pe factură {lei(vat)}."})
    if total is not None and base is not None and vat is not None:
        ok = _close(base + vat, total)
        checks.append({"name": "total", "ok": ok,
                       "message": f"Bază + TVA = {lei(base + vat)}; total pe factură {lei(total)}."})
    if fields.get("index_old") is not None and fields.get("index_new") is not None:
        diff = fields["index_new"] - fields["index_old"]
        consumed = _qty(lines, "energy_consumed")
        if consumed is not None:
            ok = abs(diff - consumed) <= 1
            checks.append({"name": "index", "ok": ok,
                           "message": f"Index nou − index vechi = {diff:g} kWh; consum pe factură {consumed:g} kWh."})
    consumed, compensated = _qty(lines, "energy_consumed"), _qty(lines, "energy_compensated")
    if consumed is not None and compensated is not None:
        ok = compensated <= consumed + 0.5
        checks.append({"name": "compensated_le_consumed", "ok": ok,
                       "message": "Energia compensată nu depășește consumul." if ok else
                       f"Energia compensată ({compensated:g} kWh) depășește consumul ({consumed:g} kWh)."})
    return checks


def apply_confidence(fields: dict, checks: list[dict]) -> float:
    """Raise money-line confidence when the arithmetic closes; lower it when it doesn't.
    Returns the overall bill confidence (0–1)."""
    lines = fields.get("lines", [])
    money_ok = [c["ok"] for c in checks if c["name"] in ("sum_lines", "vat", "total")]
    if money_ok and all(money_ok):
        for ln in lines:
            if ln.get("amount_lei") is not None:
                ln["confidence"] = max(ln["confidence"], 0.97)
    elif money_ok:
        for ln in lines:
            if ln["line_type"] in MONEY_TYPES | {"subtotal", "vat", "total"}:
                ln["confidence"] = min(ln["confidence"], 0.6)
    if any(c["name"] == "index" and c["ok"] for c in checks):
        for ln in lines:
            if ln["line_type"] == "energy_consumed":
                ln["confidence"] = max(ln["confidence"], 0.97)
    ocr = fields.get("ocr_confidence")
    if ocr is not None:
        factor = min(1.0, max(0.3, ocr / 90))
        for ln in lines:
            if not (money_ok and all(money_ok) and ln.get("amount_lei") is not None):
                ln["confidence"] = round(ln["confidence"] * factor, 2)
    confs = [ln["confidence"] for ln in lines] + [v for v in fields.get("field_confidence", {}).values()]
    return round(sum(confs) / len(confs), 2) if confs else 0.0
