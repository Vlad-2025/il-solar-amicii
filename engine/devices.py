"""Electrical devices the user adds, turned into hourly demand.

Typical values in the catalogue are rough starting points for the user to edit, not measurements.
Heating and cooling follow the outdoor temperature of the simulated year.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

LOCAL_TZ = "Europe/Bucharest"
ALL_MONTHS = list(range(1, 13))
KINDS = {
    "schedule": "Program fix (pornește la o oră, merge câteva ore)",
    "continuous": "Permanent (frigider, congelator)",
    "heating": "Încălzire (după temperatura de afară)",
    "cooling": "Răcire / aer condiționat (după temperatură)",
    "ev": "Mașină electrică (încărcare)",
}

CATALOG: list[dict] = [
    {"key": "fridge", "name": "Frigider", "kind": "continuous", "power_w": 100, "hours_per_day": 8},
    {"key": "freezer", "name": "Congelator", "kind": "continuous", "power_w": 100, "hours_per_day": 10},
    {"key": "washer", "name": "Mașină de spălat rufe", "kind": "schedule", "power_w": 2000, "hours_per_day": 1,
     "start_hour": 19, "days_per_week": 4, "flexible": True},
    {"key": "dryer", "name": "Uscător de rufe", "kind": "schedule", "power_w": 2500, "hours_per_day": 1,
     "start_hour": 20, "days_per_week": 2, "flexible": True},
    {"key": "dishwasher", "name": "Mașină de spălat vase", "kind": "schedule", "power_w": 1800, "hours_per_day": 1.2,
     "start_hour": 20, "days_per_week": 7, "flexible": True},
    {"key": "oven", "name": "Cuptor electric", "kind": "schedule", "power_w": 2500, "hours_per_day": 1,
     "start_hour": 18, "days_per_week": 4},
    {"key": "induction", "name": "Plită cu inducție", "kind": "schedule", "power_w": 2000, "hours_per_day": 1,
     "start_hour": 18, "days_per_week": 7},
    {"key": "boiler", "name": "Boiler electric (apă caldă)", "kind": "schedule", "power_w": 2000, "hours_per_day": 3,
     "start_hour": 5, "days_per_week": 7, "flexible": True},
    {"key": "ac", "name": "Aer condiționat", "kind": "cooling", "annual_kwh": 600},
    {"key": "heatpump", "name": "Pompă de căldură", "kind": "heating", "annual_kwh": 4000},
    {"key": "ev", "name": "Mașină electrică", "kind": "ev", "power_w": 7400, "start_hour": 19, "days_per_week": 7,
     "ev_km_day": 40, "ev_kwh_100km": 17, "flexible": True},
    {"key": "office", "name": "Calculator / lucru de acasă", "kind": "schedule", "power_w": 200, "hours_per_day": 8,
     "start_hour": 9, "days_per_week": 5},
    {"key": "tv", "name": "Televizor", "kind": "schedule", "power_w": 100, "hours_per_day": 4, "start_hour": 19,
     "days_per_week": 7},
    {"key": "pool", "name": "Pompă piscină", "kind": "schedule", "power_w": 750, "hours_per_day": 8, "start_hour": 10,
     "days_per_week": 7, "months": [5, 6, 7, 8, 9], "flexible": True},
    {"key": "custom", "name": "Alt aparat", "kind": "schedule", "power_w": 1000, "hours_per_day": 1, "start_hour": 18,
     "days_per_week": 7},
]

DEFAULTS = {"power_w": 0.0, "hours_per_day": 0.0, "start_hour": 18, "days_per_week": 7, "months": ALL_MONTHS,
            "flexible": False, "is_new": True, "annual_kwh": None, "ev_km_day": None, "ev_kwh_100km": None,
            "quantity": 1}


def normalize(dev: dict) -> dict:
    d = {**DEFAULTS, **{k: v for k, v in dev.items() if v is not None}}
    d["months"] = [int(m) for m in (d.get("months") or ALL_MONTHS)]
    d["start_hour"] = int(d["start_hour"]) % 24
    d["days_per_week"] = max(0, min(7, int(d["days_per_week"])))
    d["quantity"] = max(1, int(d.get("quantity") or 1))
    return d


def active_weekdays(days_per_week: int) -> set[int]:
    if days_per_week >= 7:
        return set(range(7))
    if days_per_week == 5:
        return {0, 1, 2, 3, 4}
    if days_per_week == 2:
        return {5, 6}
    return {int(x) for x in np.round(np.linspace(0, 7, days_per_week, endpoint=False))} if days_per_week else set()


def daily_kwh(dev: dict) -> float:
    d = normalize(dev)
    if d["kind"] == "ev":
        return (d["ev_km_day"] or 0) * (d["ev_kwh_100km"] or 0) / 100 / 0.9 * d["quantity"]   # 90% charging efficiency
    return d["power_w"] / 1000 * d["hours_per_day"] * d["quantity"]


def _place(local: pd.DatetimeIndex, active_day: np.ndarray, start: int, energy: float, power_kw: float) -> np.ndarray:
    """Put `energy` kWh on each active local day starting at `start`, at most power_kw per hour (wraps at midnight)."""
    out = np.zeros(len(local))
    if energy <= 0 or power_kw <= 0:
        return out
    hours, rem = int(energy // power_kw), energy - power_kw * int(energy // power_kw)
    plan = {(start + i) % 24: power_kw for i in range(min(hours, 24))}
    if rem > 1e-9 and hours < 24:
        plan[(start + hours) % 24] = plan.get((start + hours) % 24, 0) + rem
    hour = np.asarray(local.hour)
    for h, e in plan.items():
        out[(hour == h) & active_day] += e
    return out


def device_load(dev: dict, index: pd.DatetimeIndex, temp_c: pd.Series | None = None,
                start_hour: int | None = None) -> pd.Series:
    d = normalize(dev)
    local = index.tz_convert(LOCAL_TZ)
    in_months = np.isin(local.month, d["months"])
    kind = d["kind"]
    if kind == "continuous":
        vals = np.where(in_months, d["power_w"] / 1000 * d["hours_per_day"] / 24 * d["quantity"], 0.0)
    elif kind in ("heating", "cooling"):
        t = (temp_c.reindex(index).astype(float).interpolate(limit_direction="both").fillna(15.0).to_numpy()
             if temp_c is not None else np.full(len(index), 15.0))
        need = np.clip(18.0 - t, 0, None) if kind == "heating" else np.clip(t - 24.0, 0, None)
        need = need * in_months
        if need.sum() <= 0:                              # no hot hours in this year: spread over summer afternoons
            need = (np.isin(local.month, [6, 7, 8]) & (local.hour >= 12) & (local.hour < 20)).astype(float)
        vals = (d["annual_kwh"] or 0) * d["quantity"] * need / need.sum() * (len(index) / 8760.0)
    else:
        weekday_ok = np.isin(local.day_of_week, list(active_weekdays(d["days_per_week"])))
        active = in_months & weekday_ok
        if kind == "ev":
            energy, power = daily_kwh(d), max(d["power_w"], 1000) / 1000
        else:
            energy, power = d["power_w"] / 1000 * d["hours_per_day"] * d["quantity"], d["power_w"] / 1000 * d["quantity"]
        vals = _place(local, active, d["start_hour"] if start_hour is None else start_hour, energy, power)
    return pd.Series(vals, index=index, name=d.get("name"))


def total_load(devices: list[dict], index: pd.DatetimeIndex, temp_c: pd.Series | None = None,
               only_new: bool = False) -> tuple[pd.Series, list[dict]]:
    total = pd.Series(0.0, index=index)
    rows = []
    for dev in devices:
        d = normalize(dev)
        if only_new and not d["is_new"]:
            continue
        s = device_load(d, index, temp_c)
        total = total.add(s, fill_value=0.0)
        rows.append({"id": d.get("id"), "name": d.get("name"), "kind": d["kind"], "annual_kwh": round(float(s.sum()), 1),
                     "is_new": d["is_new"], "flexible": d["flexible"]})
    return total, rows


def suggest_schedule(devices: list[dict], index: pd.DatetimeIndex, surplus: pd.Series,
                     temp_c: pd.Series | None = None) -> list[dict]:
    """For flexible devices, the start hour that puts most of their energy into solar surplus.
    Devices are placed one after another, each using up the surplus it takes."""
    left = surplus.clip(lower=0).copy()
    tips = []
    for dev in devices:
        d = normalize(dev)
        if not d["flexible"] or d["kind"] not in ("schedule", "ev"):
            continue
        now = device_load(d, index, temp_c)
        covered_now = float(np.minimum(now, left).sum())
        best_h, best_cov, best_load = d["start_hour"], covered_now, now
        for h in range(6, 18):
            cand = device_load(d, index, temp_c, start_hour=h)
            cov = float(np.minimum(cand, left).sum())
            if cov > best_cov + 1e-6:
                best_h, best_cov, best_load = h, cov, cand
        left = (left - np.minimum(best_load, left)).clip(lower=0)
        if best_h != d["start_hour"] and best_cov - covered_now > 1:
            tips.append({"id": d.get("id"), "name": d.get("name"), "from_hour": d["start_hour"], "to_hour": best_h,
                         "solar_kwh_now": round(covered_now, 1), "solar_kwh_after": round(best_cov, 1),
                         "gain_kwh": round(best_cov - covered_now, 1)})
    return tips
