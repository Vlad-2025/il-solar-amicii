"""Turn a mapped export into the one hourly schema (UTC, start of hour, kWh) every model uses."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from ingest.detect import ENERGY_ROLES

TARGET = {
    "pv": "pv_kwh", "load": "load_kwh", "grid_import": "grid_import_kwh", "grid_export": "grid_export_kwh",
    "batt_charge": "batt_charge_kwh", "batt_discharge": "batt_discharge_kwh", "soc": "soc_pct",
}


def to_number(col: pd.Series) -> pd.Series:
    """Accepts 1.234,56 · 1234,56 · 1,234.56 · 1234.56 · '--' · ''."""
    def conv(x):
        if x is None:
            return np.nan
        s = str(x).strip().replace(" ", "").replace(" ", "")
        if s in ("", "-", "--", "nan", "NaN", "None", "null", "N/A"):
            return np.nan
        s = re.sub(r"[^0-9,.\-eE+]", "", s)
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
        try:
            return float(s)
        except ValueError:
            return np.nan
    return col.map(conv).astype(float)


def parse_timestamps(col: pd.Series, dayfirst: bool = True) -> pd.Series:
    s = col.astype(str).str.strip()
    numeric = pd.to_numeric(s, errors="coerce")
    if numeric.notna().mean() > 0.95:                       # epoch seconds or milliseconds
        unit = "ms" if numeric.median() > 1e11 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True)
    ts = pd.to_datetime(s, dayfirst=dayfirst, errors="coerce", format="mixed")
    return ts


def _localize(ts: pd.Series, tz: str) -> tuple[pd.Series, int]:
    """Local wall-clock time -> UTC, handling the DST jumps. Returns (utc, rows dropped)."""
    if ts.dt.tz is not None:
        return ts.dt.tz_convert("UTC"), 0
    try:
        out = ts.dt.tz_localize(tz, ambiguous="infer", nonexistent="shift_forward")
        return out.dt.tz_convert("UTC"), 0
    except Exception:  # noqa: BLE001 - pandas raises several DST error types
        out = ts.dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward")
        return out.dt.tz_convert("UTC"), int(out.isna().sum() - ts.isna().sum())


def normalize(df: pd.DataFrame, mapping: dict, units: dict, kind: str | dict = "interval", label: str = "start",
              timezone: str = "Europe/Bucharest", dayfirst: bool = True, kwp: float | None = None
              ) -> tuple[pd.DataFrame, dict]:
    if "timestamp" not in mapping:
        raise ValueError("Alegeți coloana cu data și ora.")
    energy_roles = [r for r in ENERGY_ROLES if mapping.get(r)]
    if not energy_roles:
        raise ValueError("Alegeți cel puțin o coloană de energie (producție, consum, import sau export).")

    report: dict = {"rows_in": int(len(df)), "warnings": []}
    ts = parse_timestamps(df[mapping["timestamp"]], dayfirst)
    bad_ts = int(ts.isna().sum())
    ts_utc, dst_dropped = _localize(ts, timezone)

    frame = pd.DataFrame({"ts": ts_utc})
    for role in energy_roles + (["soc"] if mapping.get("soc") else []):
        frame[role] = to_number(df[mapping[role]]).to_numpy()
    frame = frame.dropna(subset=["ts"]).sort_values("ts")
    dups = int(frame["ts"].duplicated().sum())
    frame = frame.drop_duplicates(subset="ts", keep="first").set_index("ts")
    if frame.empty:
        raise ValueError("Nu am putut citi nicio dată validă din coloana de timp.")

    step_h = float(frame.index.to_series().diff().median() / pd.Timedelta(hours=1)) if len(frame) > 1 else 1.0
    if not np.isfinite(step_h) or step_h <= 0:
        step_h = 1.0
    if label == "end":
        frame.index = frame.index - pd.Timedelta(hours=step_h)

    negatives = 0
    out = {}
    for role in energy_roles:
        v = frame[role].copy()
        unit = units.get(role, "kWh")
        role_kind = kind.get(role, "interval") if isinstance(kind, dict) else kind
        if unit in ("W", "Wh"):
            v = v / 1000.0
        if role_kind == "cumulative" and unit in ("kWh", "Wh"):
            v = v.diff()
            v[v < 0] = np.nan                                   # counter reset
            v = v.shift(-1)                                     # energy of the interval that starts here
        elif unit in ("kW", "W"):
            v = v * step_h                                      # average power -> energy per interval
        neg = v < 0
        negatives += int(neg.sum())
        out[TARGET[role]] = v.mask(neg)
    hourly = pd.DataFrame(out).resample("h").sum(min_count=1)
    if mapping.get("soc"):
        hourly["soc_pct"] = frame["soc"].resample("h").mean()

    full = pd.date_range(hourly.index.min(), hourly.index.max(), freq="h", tz="UTC", name="ts")
    hourly = hourly.reindex(full)
    gaps = int(hourly[[TARGET[r] for r in energy_roles]].isna().all(axis=1).sum())

    if kwp and "pv_kwh" in hourly:
        mx = hourly["pv_kwh"].max()
        if mx > kwp * 1.3:
            report["warnings"].append(f"Producția maximă pe oră ({mx:.1f} kWh) depășește puterea instalată "
                                      f"({kwp:g} kWp). Verificați unitatea de măsură aleasă.")
        elif mx < kwp * 0.05:
            report["warnings"].append(f"Producția maximă pe oră ({mx:.3f} kWh) este foarte mică pentru {kwp:g} kWp. "
                                      "Poate unitatea este Wh, nu kWh?")
    if bad_ts:
        report["warnings"].append(f"{bad_ts} rânduri cu dată necitibilă au fost ignorate.")
    if negatives:
        report["warnings"].append(f"{negatives} valori negative au fost ignorate.")
    report.update({
        "hours": int(len(hourly)), "start": hourly.index.min(), "end": hourly.index.max(),
        "interval_minutes": round(step_h * 60), "duplicates_removed": dups, "dst_rows_dropped": dst_dropped,
        "gap_hours": gaps, "columns": [TARGET[r] for r in energy_roles] + (["soc_pct"] if mapping.get("soc") else []),
        "totals_kwh": {TARGET[r]: round(float(hourly[TARGET[r]].sum()), 1) for r in energy_roles},
    })
    return hourly, report
