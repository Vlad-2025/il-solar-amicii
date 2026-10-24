"""Combine solar and load: hourly self-consumption, export, import; optional battery; monthly bill estimate."""
from __future__ import annotations

import calendar
from datetime import date

import numpy as np
import pandas as pd

from rules.compensation import Rule, compute_compensation

LOCAL_TZ = "Europe/Bucharest"


def simulate(pv: pd.Series, load: pd.Series, battery_kwh: float = 0.0, round_trip: float = 0.9,
             soc_start: float = 0.5, c_rate: float = 0.5) -> pd.DataFrame:
    """Greedy battery: charge from surplus up to capacity, discharge on deficit. kWh per hour."""
    pv = pv.astype(float).fillna(0).clip(lower=0)
    load = load.reindex(pv.index).astype(float).fillna(0).clip(lower=0)
    n = len(pv)
    cap = max(float(battery_kwh or 0), 0.0)
    eta = np.sqrt(round_trip)
    pmax = cap * c_rate
    soc = cap * soc_start
    cols = {k: np.zeros(n) for k in ("self_consumed", "exported", "imported", "batt_charge", "batt_discharge", "soc_kwh")}
    for i, (p, ld) in enumerate(zip(pv.to_numpy(), load.to_numpy(), strict=True)):
        direct = min(p, ld)
        surplus, deficit = p - direct, ld - direct
        charge = discharge = 0.0
        if cap > 0 and surplus > 0:
            charge = min(surplus, pmax, (cap - soc) / eta)
            soc += charge * eta
        if cap > 0 and deficit > 0:
            discharge = min(deficit, pmax, soc * eta)
            soc -= discharge / eta
        cols["self_consumed"][i] = direct + discharge
        cols["exported"][i] = surplus - charge
        cols["imported"][i] = deficit - discharge
        cols["batt_charge"][i] = charge
        cols["batt_discharge"][i] = discharge
        cols["soc_kwh"][i] = soc
    out = pd.DataFrame(cols, index=pv.index)
    out["pv"] = pv
    out["load"] = load
    return out


def daily(sim: pd.DataFrame) -> pd.DataFrame:
    local = sim.copy()
    local.index = local.index.tz_convert(LOCAL_TZ)
    cols = ["pv", "load", "self_consumed", "exported", "imported"]
    return local[cols].resample("D").sum()


def month_bounds(today: date) -> tuple[date, date]:
    last = calendar.monthrange(today.year, today.month)[1]
    return date(today.year, today.month, 1), date(today.year, today.month, last)


def month_estimate(today: date, actual: pd.DataFrame | None, forecast_sim: pd.DataFrame, rule: Rule | None,
                   carryover_kwh: float, price_lei_kwh: float | None, system_kw: float | None) -> dict:
    """Predicted energy balance for the current calendar month (local time):
    measured days so far + forecast days + the rest extrapolated from the average known day."""
    start, end = month_bounds(today)
    m_lo = pd.Timestamp(start, tz=LOCAL_TZ)
    m_hi = pd.Timestamp(end, tz=LOCAL_TZ) + pd.Timedelta(days=1)
    days_in_month = (end - start).days + 1

    parts = []
    measured_days = 0.0
    if actual is not None and not actual.empty and {"grid_import_kwh", "grid_export_kwh"} <= set(actual.columns):
        a = actual.copy()
        a.index = a.index.tz_convert(LOCAL_TZ)
        a = a[(a.index >= m_lo) & (a.index < m_hi)][["grid_import_kwh", "grid_export_kwh"]].dropna()
        if not a.empty:
            parts.append(a.rename(columns={"grid_import_kwh": "imported", "grid_export_kwh": "exported"}))
            measured_days = len(a) / 24
    f = forecast_sim.copy()
    f.index = f.index.tz_convert(LOCAL_TZ)
    f = f[(f.index >= m_lo) & (f.index < m_hi)][["imported", "exported"]]
    if parts:
        f = f[f.index > parts[0].index.max()]
    forecast_days = len(f) / 24
    parts.append(f)
    known = pd.concat(parts) if parts else pd.DataFrame(columns=["imported", "exported"])

    known_days = measured_days + forecast_days
    imported, exported = float(known["imported"].sum()), float(known["exported"].sum())
    rest_days = max(0.0, days_in_month - known_days)
    if known_days > 0 and rest_days > 0:
        imported += imported / known_days * rest_days
        exported += exported / known_days * rest_days

    comp = compute_compensation((start, end), imported, exported, carryover_kwh, rule, system_kw)
    lei = comp.billed_kwh * price_lei_kwh if price_lei_kwh else None
    return {
        "month_start": start, "month_end": end,
        "measured_days": round(measured_days, 1), "forecast_days": round(forecast_days, 1),
        "extrapolated_days": round(rest_days, 1),
        "consumed_kwh": round(imported, 1), "delivered_kwh": round(exported, 1),
        "compensated_kwh": comp.compensated_kwh, "billed_kwh": comp.billed_kwh,
        "new_carryover_kwh": comp.new_carryover_kwh, "est_lei": round(lei, 2) if lei is not None else None,
        "eligible": comp.eligible, "notes": comp.notes, "rule_id": comp.rule_id,
    }
