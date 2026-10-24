"""Synthetic demo household (Bucharest, 6 kWp, 5 kWh battery).

Deterministic: the RNG always starts at DEMO_START, so a given hour has the same value whatever the
end date. Used by the demo account and by scripts/make_demo_data.py. Replace with real exports (or
OPSD household data) as soon as interviewees share one.

The "true" system has morning shading from the east and slowly building dirt, which the physics model
doesn't know about; the learned correction should find both.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pvlib

from engine.combine import simulate
from engine.solar import Site, physics

DEMO_START = pd.Timestamp("2025-10-01", tz="Europe/Bucharest").tz_convert("UTC")
DEMO_SITE = {
    "label": "demo", "lat": 44.4268, "lon": 26.1025, "elevation": 80.0, "kwp": 6.0, "tilt": 30.0,
    "azimuth": 180.0, "inverter_kw": 5.0, "battery_kwh": 5.0, "supplier": "Furnizor Demo SA",
    "customer_type": "individual", "compensation_type": "quantity", "price_lei_kwh": 1.30,
    "monthly_kwh": 300.0, "carryover_kwh": 0.0,
}
LOCAL_TZ = "Europe/Bucharest"


def synthetic_weather(lat: float, lon: float, index: pd.DatetimeIndex, elevation: float = 0, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    loc = pvlib.location.Location(lat, lon, tz="UTC", altitude=elevation)
    mid = index + pd.Timedelta(minutes=30)
    sp = loc.get_solarposition(mid)
    cs = loc.get_clearsky(mid, solar_position=sp)

    days = pd.DatetimeIndex(sorted(set(index.tz_convert(LOCAL_TZ).normalize())))
    doy = days.day_of_year.to_numpy()
    mean_cloud = 0.45 + 0.22 * np.cos(2 * np.pi * (doy - 15) / 365)     # cloudier in winter
    daily = np.empty(len(days))
    x = 0.0
    for i in range(len(days)):                                          # AR(1) weather regimes
        x = 0.65 * x + rng.normal(0, 0.55)
        daily[i] = np.clip(mean_cloud[i] + 0.35 * np.tanh(x), 0, 1)
    day_of = index.tz_convert(LOCAL_TZ).normalize()
    c_day = pd.Series(daily, index=days).reindex(day_of).to_numpy()
    c = np.clip(c_day + rng.normal(0, 0.12, len(index)), 0, 1)

    ghi = cs["ghi"].to_numpy() * (1 - 0.75 * c ** 3.4)
    dni = cs["dni"].to_numpy() * (1 - c) ** 1.6
    cosz = np.cos(np.radians(sp["apparent_zenith"].to_numpy()))
    dhi = np.clip(ghi - dni * np.clip(cosz, 0, None), 0, None)

    doy_h = index.tz_convert(LOCAL_TZ).day_of_year.to_numpy()
    hour = index.tz_convert(LOCAL_TZ).hour.to_numpy()
    temp = 12 + 12.5 * np.sin(2 * np.pi * (doy_h - 110) / 365) + 5 * np.sin(2 * np.pi * (hour - 9) / 24) \
        - 4 * (c - 0.5) + rng.normal(0, 1.2, len(index))
    return pd.DataFrame({
        "ghi": ghi, "dni": dni, "dhi": dhi, "temp_c": temp,
        "wind_ms": np.clip(rng.gamma(2.0, 1.4, len(index)), 0, 15), "cloud_pct": 100 * c,
    }, index=index).rename_axis("ts")


def _true_pv(site: Site, w: pd.DataFrame) -> pd.Series:
    phys = physics(site, w)
    shade = np.where((phys["sun_az"] < 125) & (phys["sun_elev"] < 22), 0.55, 1.0)   # neighbour's roof, east
    days = (w.index - w.index[0]) / pd.Timedelta(days=1)
    dirt = 1 - 0.06 * ((days % 120) / 120)                                         # cleaned by rain every ~4 months
    return phys["pv_kw"] * shade * dirt


def _load(index: pd.DatetimeIndex, temp: np.ndarray, rng) -> np.ndarray:
    from engine.load import TYPICAL_PROFILE, _holiday_flags

    local = index.tz_convert(LOCAL_TZ)
    base_daily = 9.5 + 3.0 * np.cos(2 * np.pi * (local.day_of_year.to_numpy() - 15) / 365)   # winter higher
    weekend = np.where(local.day_of_week >= 5, 1.12, 1.0) * np.where(_holiday_flags(index) > 0, 1.15, 1.0)
    cooling = np.clip(temp - 26, 0, None) * 0.08                                            # AC in summer
    heating = np.clip(5 - temp, 0, None) * 0.03                                             # heat pump assist
    kwh = base_daily * TYPICAL_PROFILE[local.hour] * weekend + cooling + heating
    return np.clip(kwh * rng.lognormal(0, 0.18, len(index)), 0.05, None)


def generate(end: date, seed: int = 7, weather: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Hourly (UTC) readings and the weather behind them, from DEMO_START up to the end of `end`.
    Pass real historical weather (Open-Meteo) to get an export that matches what the app will download
    when training; otherwise synthetic weather is used."""
    end_ts = pd.Timestamp(end, tz=LOCAL_TZ).tz_convert("UTC") + pd.Timedelta(days=1)
    index = pd.date_range(DEMO_START, end_ts, freq="h", inclusive="left", tz="UTC", name="ts")
    if weather is not None:
        from engine.weather import fill_gaps
        w = fill_gaps(weather.reindex(index))
    else:
        w = synthetic_weather(DEMO_SITE["lat"], DEMO_SITE["lon"], index, DEMO_SITE["elevation"], seed)
    site = Site.from_row(DEMO_SITE)
    pv = _true_pv(site, w)
    rng = np.random.default_rng(seed + 1)
    load = pd.Series(_load(index, w["temp_c"].to_numpy(), rng), index=index)
    sim = simulate(pv, load, battery_kwh=DEMO_SITE["battery_kwh"])
    # Real hybrid inverters react with a lag, so the meter always sees a little import, and the
    # same energy then goes out as extra export. Without this the demo house would import ~0 in summer.
    lag = 0.07 * load
    readings = pd.DataFrame({
        "pv_kwh": pv.round(4), "load_kwh": load.round(4),
        "grid_import_kwh": (sim["imported"] + lag).round(4),
        "grid_export_kwh": (sim["exported"] + lag.where(pv > lag, 0)).round(4),
        "batt_charge_kwh": sim["batt_charge"].round(4), "batt_discharge_kwh": sim["batt_discharge"].round(4),
        "soc_pct": (100 * sim["soc_kwh"] / DEMO_SITE["battery_kwh"]).round(1),
    }, index=index)
    return readings, w


def to_vendor_csv(readings: pd.DataFrame) -> str:
    """The demo export as a user would download it: local time, semicolons, decimal commas."""
    local = readings.copy()
    local.index = local.index.tz_convert(LOCAL_TZ)
    out = pd.DataFrame({
        "Data si ora": local.index.strftime("%d.%m.%Y %H:%M"),
        "Productie PV (kWh)": local["pv_kwh"],
        "Consum casa (kWh)": local["load_kwh"],
        "Import retea (kWh)": local["grid_import_kwh"],
        "Export retea (kWh)": local["grid_export_kwh"],
        "Incarcare baterie (kWh)": local["batt_charge_kwh"],
        "Descarcare baterie (kWh)": local["batt_discharge_kwh"],
        "SOC baterie (%)": local["soc_pct"],
    })
    return out.to_csv(sep=";", decimal=",", index=False, float_format="%.3f")
