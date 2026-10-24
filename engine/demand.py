"""Yearly household demand for the planner: which data is good enough, and the hourly series built from it.

Order (first that applies wins):
  1. personal_full     ≥ 90% of the last 365 days of hourly household load (inverter export with consumption)
  2. personal_partial  ≥ 14 days of hourly load: level and daily shape from the user, season shape from the PSC
  3. manual            annual kWh typed in the planner
  4. bills             confirmed bills with consumption (only without panels: for prosumers the bill shows only
                       what came from the grid, not what the panels covered)
  5. profile           typical monthly kWh from the installation profile
  6. assumption        fixed fallback, clearly labelled
In "devices" mode the baseline is built only from the device list (plus a small standby load).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import devices as dev_mod
from engine.profiles import USAGE_TYPES, default_profile, unit_profile

LOCAL_TZ = "Europe/Bucharest"
FALLBACK_ANNUAL_KWH = 2400.0      # assumption, not a sourced national average
STANDBY_KW = 0.05

SOURCE_LABELS = {
    "personal_full": "Consumul dumneavoastră din ultimul an (date invertor)",
    "personal_partial": "Datele dumneavoastră, completate cu profilul distribuitorului",
    "manual": "Consumul anual introdus de dumneavoastră, cu profilul distribuitorului",
    "bills": "Consumul de pe facturi, cu profilul distribuitorului",
    "profile": "Consumul lunar din profil, cu profilul distribuitorului",
    "assumption": "Presupunere: 2.400 kWh/an cu profilul distribuitorului (introduceți consumul real)",
    "devices": "Construit din lista de aparate",
}
CONFIDENCE = {"personal_full": "ridicată", "personal_partial": "medie", "manual": "medie", "bills": "medie",
              "profile": "scăzută", "assumption": "foarte scăzută", "devices": "scăzută"}


def year_index(end_local_date=None) -> pd.DatetimeIndex:
    """The last 365 complete local days, as UTC hours."""
    end = pd.Timestamp(end_local_date or pd.Timestamp.now(tz=LOCAL_TZ).date(), tz=LOCAL_TZ)
    start = end - pd.Timedelta(days=365)
    return pd.date_range(start.tz_convert("UTC"), end.tz_convert("UTC"), freq="h", inclusive="left", name="ts")


def _hour_multipliers(personal: pd.Series, area: str) -> np.ndarray:
    """Personal daily shape relative to the PSC shape, per local hour (dampened, clipped)."""
    unit = unit_profile(personal.index, area)
    hours = personal.index.tz_convert(LOCAL_TZ).hour
    p = personal.groupby(hours).mean()
    u = unit.groupby(hours).mean()
    m = (p / p.mean()) / (u / u.mean())
    m = 1 + 0.8 * (m - 1)                                  # don't over-trust a few weeks
    return m.reindex(range(24)).fillna(1.0).clip(0.3, 3.0).to_numpy()


def _bills_annual(bills: list[dict]) -> tuple[float, int] | None:
    days = kwh = 0.0
    for b in bills:
        consumed = next((ln.get("qty_kwh") for ln in b.get("lines", [])
                         if ln.get("line_type") == "energy_consumed" and ln.get("qty_kwh") is not None), None)
        if consumed is None or not b.get("period_start") or not b.get("period_end"):
            continue
        n = (b["period_end"] - b["period_start"]).days + 1
        if n > 0:
            days += n
            kwh += float(consumed)
    return (kwh / days * 365.0, int(days)) if days >= 25 else None


def baseline(index: pd.DatetimeIndex, site: dict, settings: dict, readings: pd.DataFrame | None,
             bills: list[dict], device_list: list[dict], temp_c: pd.Series | None) -> tuple[pd.Series, dict]:
    area = settings.get("area", "urban")
    usage = settings.get("usage_type", "auto")
    shape_usage = usage if usage in USAGE_TYPES else "standard"
    notes: list[str] = []

    def pack(series, source, extra=None):
        info = {"source": source, "label": SOURCE_LABELS[source], "confidence": CONFIDENCE[source],
                "annual_kwh": round(float(series.sum()) * 8760.0 / max(len(index), 1), 0), "notes": notes,
                "usage_type": shape_usage if source not in ("personal_full",) else "personal", "area": area}
        info.update(extra or {})
        return series.rename("baseline"), info

    if settings.get("baseline_mode") == "devices":
        all_dev, _ = dev_mod.total_load(device_list, index, temp_c, only_new=False)
        notes.append("Consumul de bază este suma aparatelor din listă plus 50 W în așteptare (standby).")
        return pack(all_dev + STANDBY_KW, "devices")

    load = None
    if readings is not None and not readings.empty and "load_kwh" in readings:
        load = readings["load_kwh"].reindex(index)
    n_load = int(load.notna().sum()) if load is not None else 0

    if n_load >= 0.9 * len(index):
        how = load.index.tz_convert(LOCAL_TZ)
        week_hour = how.day_of_week * 24 + how.hour
        filled = load.fillna(load.groupby(week_hour).transform("mean"))
        if n_load < len(index):
            notes.append(f"{len(index) - n_load} ore lipsă completate cu media aceleiași ore din săptămână.")
        return pack(filled.fillna(filled.mean()), "personal_full")

    if n_load >= 14 * 24:
        have = load.dropna()
        mult = _hour_multipliers(have, area) if usage == "auto" else None
        unit = unit_profile(index, area, shape_usage, mult)
        annual = float(have.sum() / unit.reindex(have.index).sum())
        series = (unit * annual).where(load.isna(), load)
        notes.append(f"{n_load // 24} zile de date proprii; restul anului estimat cu forma sezonieră a distribuitorului.")
        if n_load < 120 * 24:
            notes.append("Cu mai puțin de 4 luni de date, diferența vară–iarnă este estimată, nu măsurată.")
        return pack(series, "personal_partial", {"days_of_data": n_load // 24})

    if settings.get("annual_kwh"):
        return pack(default_profile(index, float(settings["annual_kwh"]), area, shape_usage), "manual")

    kwp = float(site.get("kwp") or 0)
    from_bills = _bills_annual(bills)
    if from_bills and kwp <= 0:
        notes.append(f"Calculat din {from_bills[1]} zile de facturi.")
        return pack(default_profile(index, from_bills[0], area, shape_usage), "bills")
    if from_bills and kwp > 0:
        notes.append("Facturile unui prosumator arată doar energia luată din rețea, nu și ce au acoperit panourile, "
                     "deci nu le folosim pentru consumul total.")

    if site.get("monthly_kwh"):
        return pack(default_profile(index, float(site["monthly_kwh"]) * 12, area, shape_usage), "profile")

    return pack(default_profile(index, FALLBACK_ANNUAL_KWH, area, shape_usage), "assumption")
