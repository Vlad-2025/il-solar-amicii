"""Layer 2: learned correction on top of the physics model, trained on the user's own history.

Learns the ratio actual / physics per hour from sun geometry and weather, which captures what the
physics can't know: shading at certain sun angles, dirt, a wrong tilt entered at onboarding, clipping.
Two extra quantile models (10th and 90th percentile) give the uncertainty band.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

FEATURES = ["hour", "doy", "sun_elev", "sun_az", "aoi", "cloud_pct", "temp_c", "csi"]
MIN_DAYLIGHT_HOURS = 200
VERSION = "solar-hgbr-1"


def features(phys: pd.DataFrame) -> pd.DataFrame:
    idx = phys.index
    return pd.DataFrame({
        "hour": idx.hour + 0.5,
        "doy": idx.day_of_year,
        "sun_elev": phys["sun_elev"],
        "sun_az": phys["sun_az"],
        "aoi": phys["aoi"],
        "cloud_pct": phys["cloud_pct"],
        "temp_c": phys["temp_c"],
        "csi": phys["csi"],
    }, index=idx).astype(float)


def _daylight(phys: pd.DataFrame, kwp: float) -> pd.Series:
    return (phys["sun_elev"] > 3) & (phys["pv_kw"] > 0.02 * kwp)


def _model(loss: str, quantile: float | None = None) -> HistGradientBoostingRegressor:
    kw = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=20,
              l2_regularization=1.0, random_state=0)
    if loss == "quantile":
        return HistGradientBoostingRegressor(loss="quantile", quantile=quantile, **kw)
    return HistGradientBoostingRegressor(loss=loss, **kw)


@dataclass
class SolarCorrection:
    p50: HistGradientBoostingRegressor
    p10: HistGradientBoostingRegressor
    p90: HistGradientBoostingRegressor
    kwp: float
    metrics: dict = field(default_factory=dict)
    version: str = VERSION

    def ratios(self, phys: pd.DataFrame) -> pd.DataFrame:
        X = features(phys)
        r = pd.DataFrame({
            "r10": self.p10.predict(X), "r50": self.p50.predict(X), "r90": self.p90.predict(X),
        }, index=phys.index).clip(lower=0, upper=1.6)
        # keep the band ordered
        r["r10"] = np.minimum(r["r10"], r["r50"])
        r["r90"] = np.maximum(r["r90"], r["r50"])
        return r

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        joblib.dump(self, buf)
        return buf.getvalue()

    @staticmethod
    def from_bytes(b: bytes) -> "SolarCorrection":
        return joblib.load(io.BytesIO(b))


def apply(phys: pd.DataFrame, model: SolarCorrection | None, inverter_kw: float | None = None) -> pd.DataFrame:
    """pv_p10 / pv_p50 / pv_p90 in kWh per hour. Without a model: physics only, no band."""
    out = pd.DataFrame(index=phys.index)
    out["pv_physics"] = phys["pv_kw"]
    if model is None:
        out["pv_p50"] = phys["pv_kw"]
        out["pv_p10"] = np.nan
        out["pv_p90"] = np.nan
        return out
    r = model.ratios(phys)
    night = phys["pv_kw"] <= 0
    for q in ("10", "50", "90"):
        v = phys["pv_kw"] * r[f"r{q}"]
        if inverter_kw:
            v = v.clip(upper=inverter_kw)
        out[f"pv_p{q}"] = v.where(~night, 0.0)
    return out


def train(phys: pd.DataFrame, actual_pv: pd.Series, kwp: float, holdout: float = 0.2) -> SolarCorrection:
    """Fit the correction. Metrics come from a chronological hold-out (last 20%); the shipped
    models are then refit on all data."""
    actual = actual_pv.reindex(phys.index)
    mask = _daylight(phys, kwp) & actual.notna()
    if int(mask.sum()) < MIN_DAYLIGHT_HOURS:
        raise ValueError(f"Prea puține ore de zi cu date ({int(mask.sum())}); sunt necesare cel puțin {MIN_DAYLIGHT_HOURS}.")

    X_all = features(phys)
    y_all = (actual / phys["pv_kw"].where(phys["pv_kw"] > 0)).clip(0, 1.6)

    # chronological split on whole days
    days = pd.Index(phys.index[mask].normalize().unique()).sort_values()
    cut_day = days[int(len(days) * (1 - holdout))]
    train_m = mask & (phys.index < cut_day)
    test_idx = phys.index[phys.index >= cut_day]

    m50 = _model("squared_error").fit(X_all[train_m], y_all[train_m])
    pred_test = apply(phys.loc[test_idx], SolarCorrection(m50, m50, m50, kwp))["pv_p50"]
    metrics = evaluate(actual.loc[test_idx], pred_test, phys.loc[test_idx, "pv_kw"], actual, kwp)
    metrics.update({"train_hours": int(train_m.sum()), "test_from": str(cut_day.date()),
                    "data_from": str(phys.index.min().date()), "data_to": str(phys.index.max().date())})

    model = SolarCorrection(
        p50=_model("squared_error").fit(X_all[mask], y_all[mask]),
        p10=_model("quantile", 0.1).fit(X_all[mask], y_all[mask]),
        p90=_model("quantile", 0.9).fit(X_all[mask], y_all[mask]),
        kwp=kwp, metrics=metrics,
    )
    # how often actual falls inside the band (on the training data; indicative only)
    band = apply(phys[mask], model)
    inside = ((actual[mask] >= band["pv_p10"]) & (actual[mask] <= band["pv_p90"])).mean()
    model.metrics["band_coverage"] = round(float(inside), 3)
    return model


def evaluate(actual: pd.Series, corrected: pd.Series, physics_only: pd.Series, actual_full: pd.Series,
             kwp: float) -> dict:
    """MAE in kWh per hour and normalised by kWp, against two baselines: physics only, and
    'same hour yesterday' (persistence). Scored on hours where all three exist and the sun is up."""
    persistence = actual_full.shift(24).reindex(actual.index)
    frame = pd.DataFrame({"a": actual, "c": corrected, "p": physics_only, "y": persistence}).dropna()
    frame = frame[(frame["p"] > 0) | (frame["a"] > 0)]
    if frame.empty:
        return {}

    def mae(col):
        return float((frame[col] - frame["a"]).abs().mean())

    res = {
        "hours_scored": int(len(frame)),
        "mae_kwh_corrected": round(mae("c"), 4),
        "mae_kwh_physics": round(mae("p"), 4),
        "mae_kwh_persistence": round(mae("y"), 4),
    }
    for k in ("corrected", "physics", "persistence"):
        res[f"nmae_pct_{k}"] = round(100 * res[f"mae_kwh_{k}"] / kwp, 2)
    daily = frame.resample("D").sum()
    res["daily_mae_kwh_corrected"] = round(float((daily["c"] - daily["a"]).abs().mean()), 3)
    res["daily_mae_kwh_physics"] = round(float((daily["p"] - daily["a"]).abs().mean()), 3)
    return res
