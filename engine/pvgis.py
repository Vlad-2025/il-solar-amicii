"""PVGIS (EU JRC): expected annual and monthly production for the site, used once at onboarding
and to flag systems that produce far less than expected."""
from __future__ import annotations

import pandas as pd
import requests

from engine.solar import Site

PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc"


class PVGISUnavailable(RuntimeError):
    pass


def fetch(site: Site, loss_pct: float = 14.0) -> dict:
    params = {
        "lat": site.lat, "lon": site.lon, "peakpower": site.kwp, "loss": loss_pct,
        "angle": site.tilt, "aspect": site.azimuth - 180.0,   # PVGIS: 0 = south, -90 = east, 90 = west
        "outputformat": "json",
    }
    try:
        r = requests.get(PVGIS_URL, params=params, timeout=30)
        r.raise_for_status()
        out = r.json()["outputs"]
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise PVGISUnavailable(str(exc)) from exc
    monthly = {int(m["month"]): float(m["E_m"]) for m in out["monthly"]["fixed"]}
    return {"annual_kwh": float(out["totals"]["fixed"]["E_y"]), "monthly_kwh": monthly}


def compare(readings_pv: pd.Series, monthly_kwh: dict[int, float], min_coverage: float = 0.9) -> dict | None:
    """Actual vs PVGIS for calendar months with at least 90% of hours present."""
    pv = readings_pv.dropna()
    if pv.empty or not monthly_kwh:
        return None
    local = pv.copy()
    local.index = local.index.tz_convert("Europe/Bucharest")
    by_month = local.resample("MS").agg(["sum", "count"])
    rows = []
    for ts, row in by_month.iterrows():
        hours = ts.days_in_month * 24
        if row["count"] >= min_coverage * hours:
            rows.append((ts.month, row["sum"], monthly_kwh.get(ts.month) or monthly_kwh.get(str(ts.month))))
    rows = [r for r in rows if r[2]]
    if not rows:
        return None
    actual = sum(r[1] for r in rows)
    expected = sum(r[2] for r in rows)
    ratio = actual / expected if expected else None
    if ratio is None:
        msg = None
    elif ratio < 0.8:
        msg = ("Producția reală este cu mult sub estimarea PVGIS. Verificați înclinarea și orientarea "
               "introduse, sau sistemul poate funcționa sub potențial (umbră, murdărie, defect).")
    elif ratio > 1.2:
        msg = "Producția reală este peste estimarea PVGIS. Verificați puterea instalată (kWp) introdusă."
    else:
        msg = "Producția reală este în linie cu estimarea PVGIS pentru locația și panourile dumneavoastră."
    return {"months": len(rows), "actual_kwh": round(actual, 1), "expected_kwh": round(expected, 1),
            "ratio": round(ratio, 3) if ratio else None, "message": msg}
