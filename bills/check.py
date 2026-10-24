"""Check a confirmed bill against the user's inverter data and the rule in force.

Wording is always "worth checking", never "you were overcharged": the inverter is not the official meter.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from rules.compensation import Rule, compute_compensation


def _pct(x: float) -> str:
    return f"{x:+.1f}%".replace(".", ",")

LOCAL_TZ = "Europe/Bucharest"


def _qty(lines, t):
    vals = [ln.get("qty_kwh") for ln in lines if ln.get("line_type") == t and ln.get("qty_kwh") is not None]
    return float(vals[0]) if vals else None


def _period_slice(readings: pd.DataFrame, start: date, end: date) -> tuple[pd.DataFrame, float]:
    lo = pd.Timestamp(start, tz=LOCAL_TZ).tz_convert("UTC")
    hi = pd.Timestamp(end + timedelta(days=1), tz=LOCAL_TZ).tz_convert("UTC")
    part = readings[(readings.index >= lo) & (readings.index < hi)]
    hours = (hi - lo) / pd.Timedelta(hours=1)
    return part, (len(part) / hours if hours else 0.0)


def _compare(check_type: str, label: str, bill_val: float, inv_val: float, threshold_pct: float) -> dict:
    diff_pct = (bill_val - inv_val) / inv_val * 100 if inv_val else None
    if diff_pct is None:
        sev, msg = "info", f"{label}: invertorul nu a înregistrat energie în perioadă; nu putem compara."
    elif abs(diff_pct) > threshold_pct:
        sev = "worth_checking"
        msg = (f"{label} de pe factură ({bill_val:.0f} kWh) diferă de datele invertorului ({inv_val:.0f} kWh) "
               f"cu {_pct(diff_pct)}. Merită verificat cu furnizorul (invertorul nu este contorul oficial).")
    else:
        sev = "ok"
        msg = f"{label}: factura ({bill_val:.0f} kWh) și invertorul ({inv_val:.0f} kWh) se potrivesc ({_pct(diff_pct)})."
    return {"check_type": check_type, "expected": round(inv_val, 2), "actual": round(bill_val, 2),
            "diff_pct": round(diff_pct, 2) if diff_pct is not None else None, "severity": sev, "message": msg}


def check_bill(bill: dict, readings: pd.DataFrame, rule: Rule | None, carried_in_kwh: float | None,
               system_kw: float | None, threshold_pct: float = 10.0) -> list[dict]:
    lines = bill.get("lines", [])
    start, end = bill.get("period_start"), bill.get("period_end")
    checks: list[dict] = []
    if not start or not end:
        return [{"check_type": "period", "severity": "info", "message": "Lipsește perioada de facturare; confirmați-o mai întâi."}]

    part, coverage = _period_slice(readings, start, end) if not readings.empty else (readings, 0.0)
    delivered, consumed = _qty(lines, "energy_delivered"), _qty(lines, "energy_consumed")
    compensated = _qty(lines, "energy_compensated")

    if coverage < 0.9:
        checks.append({"check_type": "coverage", "expected": None, "actual": round(coverage * 100, 1), "diff_pct": None,
                       "severity": "info",
                       "message": f"Datele de la invertor acoperă doar {coverage:.0%} din perioada facturii; "
                                  "comparația cu invertorul nu este sigură."})
    if coverage > 0.5:
        scale = 1 / coverage if coverage < 1 else 1.0
        if delivered is not None and part["grid_export_kwh"].notna().any():
            checks.append(_compare("delivered_vs_inverter", "Energia livrată",
                                   delivered, float(part["grid_export_kwh"].sum()) * scale, threshold_pct))
        if consumed is not None and part["grid_import_kwh"].notna().any():
            checks.append(_compare("consumed_vs_inverter", "Energia consumată din rețea",
                                   consumed, float(part["grid_import_kwh"].sum()) * scale, threshold_pct))

    if consumed is not None and delivered is not None and rule is not None:
        res = compute_compensation((start, end), consumed, delivered, carried_in_kwh or 0.0, rule, system_kw)
        if compensated is not None:
            diff = compensated - res.compensated_kwh
            sev = "worth_checking" if abs(diff) > 1 else "ok"
            msg = (f"Recalculat după {rule.label}: compensare așteptată {res.compensated_kwh:.0f} kWh, pe factură "
                   f"{compensated:.0f} kWh." + (" Merită verificat." if sev != "ok" else " Se potrivește."))
            if carried_in_kwh is None:
                msg += " (Fără creditul reportat din luna anterioară, pe care nu îl cunoaștem.)"
            checks.append({"check_type": "compensation", "expected": res.compensated_kwh, "actual": compensated,
                           "diff_pct": round(diff / res.compensated_kwh * 100, 2) if res.compensated_kwh else None,
                           "severity": sev, "message": msg})
        checks.append({"check_type": "rule_notes", "expected": None, "actual": None, "diff_pct": None, "severity": "info",
                       "message": " ".join(res.notes) or "Fără observații."})
    return checks
