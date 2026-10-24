"""Weather from Open-Meteo (free, no key; non-commercial use).

Convention used everywhere in the engine: hourly rows are indexed by the START of the hour, in UTC.
Open-Meteo labels radiation with the END of the averaging hour, so its index is shifted back 1 hour.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"

HOURLY = {
    "shortwave_radiation": "ghi",
    "direct_normal_irradiance": "dni",
    "diffuse_radiation": "dhi",
    "temperature_2m": "temp_c",
    "wind_speed_10m": "wind_ms",
    "cloud_cover": "cloud_pct",
}
COLUMNS = list(HOURLY.values())
TIMEOUT = 25


class WeatherUnavailable(RuntimeError):
    pass


def _to_frame(payload: dict) -> pd.DataFrame:
    hourly = payload.get("hourly") or {}
    if "time" not in hourly:
        raise WeatherUnavailable(payload.get("reason", "Open-Meteo returned no hourly data"))
    idx = pd.to_datetime(hourly["time"], utc=True) - pd.Timedelta(hours=1)  # end-of-hour -> start-of-hour
    df = pd.DataFrame({new: hourly.get(old) for old, new in HOURLY.items()}, index=idx).astype(float)
    df.index.name = "ts"
    return df


def _get(url: str, params: dict) -> dict:
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeatherUnavailable(str(exc)) from exc


def fetch_forecast(lat: float, lon: float, days: int = 7, past_days: int = 0) -> pd.DataFrame:
    params = {
        "latitude": lat, "longitude": lon, "hourly": ",".join(HOURLY),
        "forecast_days": min(max(days, 1), 16), "past_days": min(max(past_days, 0), 92),
        "timezone": "UTC", "wind_speed_unit": "ms",
    }
    return _to_frame(_get(FORECAST_URL, params))


def fetch_historical(lat: float, lon: float, start: date, end: date) -> pd.DataFrame:
    """Hourly weather for [start, end] (dates, inclusive). Archive for older days, forecast API's
    past_days for the last week (the archive lags a few days)."""
    today = date.today()
    archive_end = min(end, today - timedelta(days=6))
    frames = []
    if start <= archive_end:
        params = {
            "latitude": lat, "longitude": lon, "hourly": ",".join(HOURLY),
            "start_date": start.isoformat(), "end_date": archive_end.isoformat(),
            "timezone": "UTC", "wind_speed_unit": "ms",
        }
        frames.append(_to_frame(_get(ARCHIVE_URL, params)))
    if end > archive_end:
        recent = fetch_forecast(lat, lon, days=1, past_days=min(92, (today - max(start, archive_end)).days + 1))
        frames.append(recent)
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.concat(frames)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return df[(df.index >= lo) & (df.index < hi)]


def clear_sky_weather(lat: float, lon: float, index: pd.DatetimeIndex, elevation: float = 0,
                      temp_c: float = 15.0, cloud_factor: float = 1.0) -> pd.DataFrame:
    """Fallback when Open-Meteo is unreachable: clear-sky irradiance (pvlib Ineichen), fixed temperature."""
    from pvlib.location import Location

    loc = Location(lat, lon, tz="UTC", altitude=elevation)
    cs = loc.get_clearsky(index + pd.Timedelta(minutes=30))
    cs.index = index
    df = pd.DataFrame({
        "ghi": cs["ghi"] * cloud_factor, "dni": cs["dni"] * cloud_factor, "dhi": cs["dhi"],
        "temp_c": temp_c, "wind_ms": 2.0, "cloud_pct": 0.0 if cloud_factor >= 1 else 50.0,
    }, index=index)
    df.index.name = "ts"
    return df


def future_index(days: int = 7, now: pd.Timestamp | None = None) -> pd.DatetimeIndex:
    now = (now or pd.Timestamp.now(tz="UTC")).floor("h")
    return pd.date_range(now, periods=24 * days, freq="h", tz="UTC", name="ts")


def geocode(query: str, count: int = 5) -> list[dict]:
    try:
        data = _get(GEOCODE_URL, {"name": query, "count": count, "language": "ro", "format": "json"})
    except WeatherUnavailable:
        return []
    return [{"name": r.get("name"), "admin": r.get("admin1"), "country": r.get("country"),
             "lat": r["latitude"], "lon": r["longitude"], "elevation": r.get("elevation")}
            for r in data.get("results", []) or []]


def elevation(lat: float, lon: float) -> float | None:
    try:
        data = _get(ELEVATION_URL, {"latitude": lat, "longitude": lon})
        vals = data.get("elevation") or []
        return float(vals[0]) if vals else None
    except WeatherUnavailable:
        return None


def fill_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Short gaps: interpolate up to 3 h; radiation at night stays 0."""
    out = df.astype(float).interpolate(limit=3, limit_direction="both")
    for c in ("ghi", "dni", "dhi"):
        if c in out:
            out[c] = out[c].clip(lower=0).fillna(0)
    for c, default in (("temp_c", 15.0), ("wind_ms", 2.0), ("cloud_pct", 50.0)):
        if c in out:
            out[c] = out[c].fillna(default)
    return out.replace([np.inf, -np.inf], np.nan).fillna(0)
