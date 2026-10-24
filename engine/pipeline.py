"""End-to-end forecast and training, shared by the app and the scheduled jobs. No Streamlit here."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from db import repo
from engine import calibrate, combine, load as loadmod, weather
from engine.solar import Site, physics
from rules.compensation import Rule, load_rules, rule_for

DEFAULT_MONTHLY_KWH = 250.0


def is_demo(site_row: dict) -> bool:
    return (site_row.get("label") or "") == "demo"


def weather_kind(site_row: dict) -> str:
    # The demo account's history was generated from synthetic weather stored under kind="demo",
    # so training on it stays consistent and never mixes with real users' cached weather.
    return "demo" if is_demo(site_row) else "historical"


def all_rules() -> list[Rule]:
    """Rules in force for calculations. DEMO rules never take part, even if someone published one."""
    try:
        rows = repo.list_rules()
    except Exception:  # noqa: BLE001 - database not initialised yet: the rule files are the source of truth
        rows = []
    rules = [Rule.from_dict(r) for r in rows] if rows else load_rules()
    return [r for r in rules if not r.demo]


# ---------------------------------------------------------------- weather
def forecast_weather(site_row: dict, days: int = 7) -> tuple[pd.DataFrame, str]:
    idx = weather.future_index(days)
    try:
        w = weather.fetch_forecast(site_row["lat"], site_row["lon"], days=days + 1)
        w = weather.fill_gaps(w.reindex(idx))
        return w, "Open-Meteo"
    except weather.WeatherUnavailable:
        w = weather.clear_sky_weather(site_row["lat"], site_row["lon"], idx, site_row.get("elevation") or 0,
                                      cloud_factor=0.75)
        return w, "cer senin estimat (Open-Meteo indisponibil)"


def historical_weather(site_row: dict, start: date, end: date) -> pd.DataFrame:
    """Cached in the weather table; only missing days are fetched."""
    kind = weather_kind(site_row)
    lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    cached = repo.load_weather(site_row["lat"], site_row["lon"], lo, hi, kind)
    expected = int((hi - lo) / pd.Timedelta(hours=1))
    if kind == "demo" or len(cached) >= expected * 0.98:
        return weather.fill_gaps(cached.reindex(pd.date_range(lo, hi, freq="h", inclusive="left", tz="UTC")))
    fresh = weather.fetch_historical(site_row["lat"], site_row["lon"], start, end)
    repo.save_weather(site_row["lat"], site_row["lon"], fresh, kind)
    idx = pd.date_range(lo, hi, freq="h", inclusive="left", tz="UTC")
    return weather.fill_gaps(fresh.reindex(idx))


# ---------------------------------------------------------------- training
def train_models(site_row: dict) -> dict:
    """Train the solar correction and the load model from the site's readings. Returns a report."""
    site = Site.from_row(site_row)
    readings = repo.load_readings(site_row["id"])
    report: dict = {}
    if readings.empty:
        return {"solar": {"error": "Nu există date de la invertor."}, "load": {"error": "Nu există date."}}

    start, end = readings.index.min().date(), readings.index.max().date()
    try:
        w = historical_weather(site_row, start, end)
    except weather.WeatherUnavailable as exc:
        return {"solar": {"error": f"Vremea istorică nu este disponibilă: {exc}"},
                "load": {"error": "Vremea istorică nu este disponibilă."}}

    phys = physics(site, w)
    if readings["pv_kwh"].notna().sum() > 0:
        try:
            model = calibrate.train(phys, readings["pv_kwh"], site.kwp)
            repo.save_model(site_row["id"], "solar", model.to_bytes(), model.metrics)
            report["solar"] = model.metrics
        except ValueError as exc:
            report["solar"] = {"error": str(exc)}
    else:
        report["solar"] = {"error": "Exportul nu conține producția PV."}

    if readings["load_kwh"].notna().sum() > 0:
        try:
            lm = loadmod.train(readings["load_kwh"], w["temp_c"])
            repo.save_model(site_row["id"], "load", lm.to_bytes(), lm.metrics)
            report["load"] = lm.metrics
        except ValueError as exc:
            report["load"] = {"error": str(exc)}
    else:
        report["load"] = {"error": "Exportul nu conține consumul casei; folosim profilul tipic scalat la factură."}
    return report


# ---------------------------------------------------------------- forecast
def _monthly_kwh_estimate(site_row: dict, readings: pd.DataFrame, month: int) -> tuple[float, str]:
    if not readings.empty and readings["load_kwh"].notna().sum() >= 24 * 7:
        s = readings["load_kwh"].dropna()
        local = s.copy()
        local.index = local.index.tz_convert(loadmod.LOCAL_TZ)
        same = local[local.index.month == month]
        if len(same) >= 24 * 7:
            return float(same.mean() * 24 * 30.4), "media aceleiași luni din istoricul dumneavoastră"
        recent = local.iloc[-24 * 28:]
        return float(recent.mean() * 24 * 30.4), "media ultimelor 4 săptămâni din istoric"
    if site_row.get("monthly_kwh"):
        return float(site_row["monthly_kwh"]), "consumul lunar introdus în profil"
    return DEFAULT_MONTHLY_KWH, f"valoare implicită ({DEFAULT_MONTHLY_KWH:g} kWh/lună)"


def run_forecast(site_row: dict, days: int = 7, save: bool = True, today: date | None = None) -> dict:
    site = Site.from_row(site_row)
    w, w_source = forecast_weather(site_row, days)
    phys = physics(site, w)

    solar_row = repo.load_model(site_row["id"], "solar")
    solar_model = calibrate.SolarCorrection.from_bytes(solar_row["artifact"]) if solar_row else None
    pv = calibrate.apply(phys, solar_model, site.inverter_kw)

    readings = repo.load_readings(site_row["id"], start=pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=400))
    load_row = repo.load_model(site_row["id"], "load")
    load_method = None
    if load_row is not None and not readings.empty:
        hist = readings["load_kwh"].dropna()
        fresh = not hist.empty and hist.index.max() >= w.index.min() - pd.Timedelta(hours=48)
        if fresh:
            lm = loadmod.LoadModel.from_bytes(load_row["artifact"])
            load = loadmod.forecast(lm, hist, w.index, w["temp_c"])
            load_method = "model antrenat pe consumul dumneavoastră"
    if load_method is None:
        local_month = w.index[0].tz_convert(loadmod.LOCAL_TZ).month
        monthly, why = _monthly_kwh_estimate(site_row, readings, local_month)
        load = loadmod.profile(w.index, monthly)
        load_method = f"profil tipic scalat la {monthly:.0f} kWh/lună ({why})"

    sim = combine.simulate(pv["pv_p50"], load, battery_kwh=site_row.get("battery_kwh") or 0)
    df = pd.concat([pv, load.rename("load_p50"), sim.drop(columns=["pv", "load"])], axis=1)

    today = today or date.today()
    rule = rule_for(today, site_row.get("customer_type") or "individual", site.kwp, all_rules())
    month = combine.month_estimate(today, readings, sim, rule, site_row.get("carryover_kwh") or 0.0,
                                   site_row.get("price_lei_kwh"), site.kwp)
    version = (solar_model.version if solar_model else "physics-only") + "+" + \
              ("load-model" if load_row is not None and load_method.startswith("model") else "load-profile")
    if save:
        repo.save_forecast(site_row["id"], df, version)
    return {
        "hourly": df, "daily": combine.daily(sim), "weather_source": w_source, "model_version": version,
        "load_method": load_method, "month": month, "rule": rule,
        "solar_metrics": solar_row["metrics_json"] if solar_row else None,
        "load_metrics": load_row["metrics_json"] if load_row else None,
        "lead_note": "Prognoza depinde de prognoza meteo: bună pentru următoarele 1–2 zile, mai slabă spre zilele 5–7.",
    }


def recent_week(site_row: dict) -> pd.DataFrame:
    lo = pd.Timestamp.now(tz="UTC").floor("D") - pd.Timedelta(days=7)
    return repo.load_readings(site_row["id"], start=lo)


def month_actuals(site_row: dict, months: int = 12) -> pd.DataFrame:
    """Monthly totals from readings (local months)."""
    r = repo.load_readings(site_row["id"])
    if r.empty:
        return pd.DataFrame()
    r.index = r.index.tz_convert(loadmod.LOCAL_TZ)
    out = r.resample("MS").sum(min_count=1)[["pv_kwh", "load_kwh", "grid_import_kwh", "grid_export_kwh"]]
    return out.iloc[-months:]


def safe_float(x) -> float | None:
    try:
        v = float(x)
        return None if np.isnan(v) else v
    except (TypeError, ValueError):
        return None


def yesterday() -> date:
    return date.today() - timedelta(days=1)
