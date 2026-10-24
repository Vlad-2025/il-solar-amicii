"""Default household load shapes from Romanian distributors' standard profiles (PSC), urban and rural.

The PSC gives how a day's energy is spread over the day (15-minute shares, aggregated here to hours) for
working / non-working days in the cold (Oct–Mar) and warm (Apr–Sep) season, plus the working/non-working
energy ratio. It does NOT give the level: annual kWh comes from the user's data, bills or profile.

"day" and "night" usage types are our own adjustments of the average shape, not measured profiles.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import holidays
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent / "data"
LOCAL_TZ = "Europe/Bucharest"
COLD_MONTHS = {10, 11, 12, 1, 2, 3}
# working-day energy / non-working-day energy, as printed in the PSC documents
RATIO = {"urban": {"cold": 0.98320042, "warm": 0.99860899}, "rural": {"cold": 0.97187165, "warm": 0.98774248}}
AREAS = {"urban": "Urban", "rural": "Rural"}
USAGE_TYPES = {
    "standard": "Profil mediu al gospodăriilor (date distribuitor, 2019)",
    "day": "Acasă în timpul zilei (lucru de acasă, pensionari) – ajustare estimată",
    "night": "Plecați ziua, consum mai mult seara – ajustare estimată",
}


@lru_cache(maxsize=4)
def hourly_shapes(area: str = "urban") -> pd.DataFrame:
    """24 rows (local hour) x 4 columns, each column sums to 1."""
    df = pd.read_csv(DATA / f"psc_{area}_2019.csv", comment="#")
    hourly = df.drop(columns="interval").groupby((df["interval"] - 1) // 4).sum()
    hourly.index.name = "hour"
    return hourly / hourly.sum()


def _adjust(shapes: pd.DataFrame, usage: str) -> pd.DataFrame:
    s = shapes.copy()
    if usage == "day":
        s.iloc[8:17] *= 1.4
    elif usage == "night":
        s.iloc[8:17] *= 0.6
        s.iloc[18:23] *= 1.15
    return s / s.sum()


def _flags(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DatetimeIndex]:
    local = index.tz_convert(LOCAL_TZ)
    ro = holidays.country_holidays("RO", years=sorted(set(local.year)))
    cold = np.isin(local.month, list(COLD_MONTHS))
    working = (local.day_of_week < 5) & ~np.array([d in ro for d in local.date])
    return cold, working, np.asarray(local.hour), local


def unit_profile(index: pd.DatetimeIndex, area: str = "urban", usage: str = "standard",
                 hour_multipliers: np.ndarray | None = None) -> pd.Series:
    """Shape over `index` (UTC hours) with the right season/day-type curve, scaled to sum to len(index)/8760
    (i.e. 1 kWh per full year)."""
    shapes = _adjust(hourly_shapes(area), usage)
    if hour_multipliers is not None:
        shapes = shapes.mul(hour_multipliers, axis=0)
        shapes = shapes / shapes.sum()
    cold, working, hour, _ = _flags(index)
    col = np.where(cold, np.where(working, "working_cold", "nonworking_cold"),
                   np.where(working, "working_warm", "nonworking_warm"))
    share = np.array([shapes.at[h, c] for h, c in zip(hour, col, strict=True)])
    r = np.where(cold, RATIO[area]["cold"], RATIO[area]["warm"])
    day_weight = np.where(working, 1.0, 1.0 / r)         # non-working days use slightly more energy
    vals = share * day_weight
    vals = vals / vals.sum() * (len(index) / 8760.0)
    return pd.Series(vals, index=index)


def default_profile(index: pd.DatetimeIndex, annual_kwh: float, area: str = "urban", usage: str = "standard",
                    hour_multipliers: np.ndarray | None = None) -> pd.Series:
    return unit_profile(index, area, usage, hour_multipliers) * annual_kwh
