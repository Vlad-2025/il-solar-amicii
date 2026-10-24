"""JSON-safe conversion: dates to ISO strings, NaN to null, numpy scalars to Python."""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd

LOCAL_TZ = "Europe/Bucharest"


def clean(obj):
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, bytes):
        return None
    return obj


def frame_records(df: pd.DataFrame, cols: list[str], local: bool = True) -> list[dict]:
    out = df[[c for c in cols if c in df.columns]].copy()
    idx = out.index.tz_convert(LOCAL_TZ) if local and out.index.tz is not None else out.index
    out.insert(0, "ts", [ts.isoformat() for ts in idx])
    return clean(out.reset_index(drop=True).to_dict(orient="records"))
