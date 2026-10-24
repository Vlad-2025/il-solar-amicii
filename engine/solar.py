"""Layer 1: physics model (pvlib). Works from day one, no history needed.

Output per hour (index = start of hour, UTC): pv_kw = average AC power over the hour = kWh in that hour.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pvlib


@dataclass
class Site:
    lat: float
    lon: float
    kwp: float
    tilt: float
    azimuth: float              # compass degrees, 180 = south (pvlib convention)
    elevation: float = 0.0
    inverter_kw: float | None = None
    losses: float = 0.14        # wiring, soiling, mismatch, availability
    gamma_pdc: float = -0.004   # power temperature coefficient, 1/°C
    inverter_eff: float = 0.96
    albedo: float = 0.2

    @classmethod
    def from_row(cls, row: dict) -> "Site":
        return cls(lat=float(row["lat"]), lon=float(row["lon"]), kwp=float(row["kwp"]),
                   tilt=float(row["tilt"]), azimuth=float(row["azimuth"]),
                   elevation=float(row.get("elevation") or 0.0),
                   inverter_kw=float(row["inverter_kw"]) if row.get("inverter_kw") else None)


def geometry(site: Site, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Sun position at the middle of each hour, angle of incidence on the panels, clear-sky GHI."""
    mid = index + pd.Timedelta(minutes=30)
    sp = pvlib.solarposition.get_solarposition(mid, site.lat, site.lon, altitude=site.elevation)
    loc = pvlib.location.Location(site.lat, site.lon, tz="UTC", altitude=site.elevation)
    cs = loc.get_clearsky(mid, solar_position=sp)
    aoi = pvlib.irradiance.aoi(site.tilt, site.azimuth, sp["apparent_zenith"], sp["azimuth"])
    out = pd.DataFrame({
        "zenith": sp["apparent_zenith"].to_numpy(),
        "sun_elev": sp["apparent_elevation"].to_numpy(),
        "sun_az": sp["azimuth"].to_numpy(),
        "aoi": np.asarray(aoi),
        "cs_ghi": cs["ghi"].to_numpy(),
    }, index=index)
    return out


def physics(site: Site, weather: pd.DataFrame) -> pd.DataFrame:
    """Hourly AC energy from weather (ghi, dni, dhi, temp_c, wind_ms). Returns geometry columns too,
    which the learned correction uses as features."""
    w = weather.reindex(columns=["ghi", "dni", "dhi", "temp_c", "wind_ms", "cloud_pct"]).astype(float)
    w = w.fillna({"ghi": 0, "dni": 0, "dhi": 0, "temp_c": 15, "wind_ms": 2, "cloud_pct": 50})
    g = geometry(site, w.index)

    dni = w["dni"].where(g["zenith"] < 87, 0.0)          # DNI near the horizon is unreliable
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=site.tilt, surface_azimuth=site.azimuth,
        solar_zenith=g["zenith"], solar_azimuth=g["sun_az"],
        dni=dni, ghi=w["ghi"], dhi=w["dhi"], albedo=site.albedo, model="isotropic",
    ).fillna(0.0)

    iam = pd.Series(pvlib.iam.physical(g["aoi"]), index=w.index).fillna(0.0)
    poa_eff = (poa["poa_direct"] * iam + poa["poa_diffuse"]).clip(lower=0)
    t_cell = pvlib.temperature.faiman(poa["poa_global"], w["temp_c"], w["wind_ms"])

    pdc = pvlib.pvsystem.pvwatts_dc(poa_eff, t_cell, pdc0=site.kwp * 1000.0, gamma_pdc=site.gamma_pdc)
    pac = pdc * (1 - site.losses) * site.inverter_eff
    if site.inverter_kw:
        pac = np.minimum(pac, site.inverter_kw * 1000.0)
    pv_kw = (pd.Series(pac, index=w.index).clip(lower=0) / 1000.0).fillna(0.0)

    csi = np.where(g["cs_ghi"] > 20, w["ghi"] / g["cs_ghi"].replace(0, np.nan), 0.0)
    out = g.copy()
    out["poa"] = poa["poa_global"]
    out["t_cell"] = t_cell
    out["cloud_pct"] = w["cloud_pct"]
    out["temp_c"] = w["temp_c"]
    out["csi"] = np.clip(np.nan_to_num(csi), 0, 1.5)
    out["pv_kw"] = pv_kw
    return out


def clear_sky_daily_kwh(site: Site, day: pd.Timestamp) -> float:
    """Upper bound used to sanity-check uploaded production."""
    idx = pd.date_range(day.normalize(), periods=24, freq="h", tz="UTC")
    cs = pvlib.location.Location(site.lat, site.lon, altitude=site.elevation).get_clearsky(idx + pd.Timedelta(minutes=30))
    cs.index = idx
    w = pd.DataFrame({"ghi": cs["ghi"], "dni": cs["dni"], "dhi": cs["dhi"], "temp_c": 20.0, "wind_ms": 2.0,
                      "cloud_pct": 0.0}, index=idx)
    return float(physics(site, w)["pv_kw"].sum())
