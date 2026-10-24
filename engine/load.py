"""Household consumption forecast.

With load history (needs the meter at the grid connection): gradient boosting on calendar, temperature
and lag features, forecast one day at a time so yesterday's (predicted) values feed the next day.
Without history: a typical household profile scaled to the monthly kWh from the user's bills.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import holidays
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

LOCAL_TZ = "Europe/Bucharest"
FEATURES = ["hour", "weekday", "month", "holiday", "temp_c", "lag24", "lag168", "roll7d"]
VERSION = "load-hgbr-1"
MIN_HOURS = 24 * 21

# Typical Romanian household day (share of daily kWh per local hour): low at night, morning bump,
# evening peak 18-22. Placeholder until replaced with a measured profile (e.g. OPSD households).
TYPICAL_PROFILE = np.array([
    2.6, 2.3, 2.2, 2.1, 2.1, 2.4, 3.3, 4.4, 4.6, 4.2, 4.0, 4.0,
    4.2, 4.1, 3.9, 3.9, 4.2, 5.0, 6.0, 6.7, 6.8, 6.2, 4.9, 3.5,
])
TYPICAL_PROFILE = TYPICAL_PROFILE / TYPICAL_PROFILE.sum()


def _holiday_flags(index: pd.DatetimeIndex) -> np.ndarray:
    local = index.tz_convert(LOCAL_TZ)
    years = sorted(set(local.year))
    ro = holidays.country_holidays("RO", years=years)
    return np.array([d in ro for d in local.date], dtype=float)


def feature_frame(series: pd.Series, temp: pd.Series) -> pd.DataFrame:
    """series: hourly load (kWh), continuous UTC index; temp aligned to the same index."""
    local = series.index.tz_convert(LOCAL_TZ)
    return pd.DataFrame({
        "hour": local.hour,
        "weekday": local.day_of_week,
        "month": local.month,
        "holiday": _holiday_flags(series.index),
        "temp_c": temp.reindex(series.index).astype(float).to_numpy(),
        "lag24": series.shift(24).to_numpy(),
        "lag168": series.shift(168).to_numpy(),
        "roll7d": series.shift(24).rolling(168, min_periods=24).mean().to_numpy(),
    }, index=series.index).astype(float)


def baseline(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Average of the same local hour and weekday over the 4 weeks before each target hour."""
    out = []
    for ts in index:
        past = [ts - pd.Timedelta(weeks=k) for k in range(1, 5)]
        vals = series.reindex(past).dropna()
        out.append(vals.mean() if len(vals) else np.nan)
    return pd.Series(out, index=index)


@dataclass
class LoadModel:
    model: HistGradientBoostingRegressor
    metrics: dict = field(default_factory=dict)
    version: str = VERSION

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        joblib.dump(self, buf)
        return buf.getvalue()

    @staticmethod
    def from_bytes(b: bytes) -> "LoadModel":
        return joblib.load(io.BytesIO(b))


def _fit(X: pd.DataFrame, y: pd.Series) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                         min_samples_leaf=20, l2_regularization=1.0,
                                         random_state=0).fit(X, y)


def train(load: pd.Series, temp: pd.Series, holdout: float = 0.2) -> LoadModel:
    s = load.astype(float).asfreq("h")
    if int(s.notna().sum()) < MIN_HOURS:
        raise ValueError(f"Prea puține ore cu consum ({int(s.notna().sum())}); sunt necesare cel puțin {MIN_HOURS} (3 săptămâni).")
    X = feature_frame(s, temp)
    ok = s.notna() & X[["lag24", "lag168", "roll7d"]].notna().all(axis=1)
    idx = s.index[ok]
    cut = idx[int(len(idx) * (1 - holdout))]
    tr, te = ok & (s.index < cut), ok & (s.index >= cut)

    m = _fit(X[tr], s[tr])
    pred = pd.Series(m.predict(X[te]), index=s.index[te]).clip(lower=0)
    base = baseline(s, s.index[te])
    frame = pd.DataFrame({"a": s[te], "m": pred, "b": base}).dropna()
    metrics = {
        "hours_scored": int(len(frame)),
        "mae_kwh_model": round(float((frame["m"] - frame["a"]).abs().mean()), 4),
        "mae_kwh_baseline": round(float((frame["b"] - frame["a"]).abs().mean()), 4),
        "test_from": str(cut.date()),
        "note": "Scor pe ora următoare cu valori reale ca intrări; prognoza pe 7 zile este mai puțin precisă.",
    }
    return LoadModel(model=_fit(X[ok], s[ok]), metrics=metrics)


def forecast(model: LoadModel, history: pd.Series, future: pd.DatetimeIndex, future_temp: pd.Series,
             history_temp: pd.Series | None = None) -> pd.Series:
    """Recursive: predict one day, append it, predict the next."""
    hist = history.astype(float).asfreq("h").iloc[-24 * 14:]
    full_idx = hist.index.union(future)
    series = hist.reindex(full_idx)
    temp = pd.concat([history_temp if history_temp is not None else pd.Series(dtype=float), future_temp])
    temp = temp[~temp.index.duplicated(keep="last")].reindex(full_idx).astype(float)
    temp = temp.interpolate(limit_direction="both").fillna(15.0)

    day_starts = pd.DatetimeIndex(sorted(set(future.floor("D"))))
    for d in day_starts:
        day_idx = future[(future >= d) & (future < d + pd.Timedelta(days=1))]
        X = feature_frame(series, temp).loc[day_idx]
        # missing lags (gaps in history): fall back to the rolling mean
        for c in ("lag24", "lag168"):
            X[c] = X[c].fillna(X["roll7d"])
        X = X.fillna(X.mean(numeric_only=True)).fillna(0)
        series.loc[day_idx] = np.clip(model.model.predict(X), 0, None)
    return series.loc[future].rename("load_p50")


def profile(future: pd.DatetimeIndex, monthly_kwh: float) -> pd.Series:
    """Typical profile scaled so each local day sums to monthly_kwh / days in that month."""
    local = future.tz_convert(LOCAL_TZ)
    daily = monthly_kwh / local.days_in_month.to_numpy()
    return pd.Series(daily * TYPICAL_PROFILE[local.hour], index=future, name="load_p50")
