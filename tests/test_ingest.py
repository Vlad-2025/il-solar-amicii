import io
import json

import numpy as np
import pandas as pd
import pytest

from ingest.demo import to_vendor_csv
from ingest.detect import guess_mapping, read_table
from ingest.normalize import normalize, to_number


def test_numbers():
    s = pd.Series(["1.234,56", "1234,56", "1,234.56", "12.5", "--", "", "3 400,5"])
    out = to_number(s).tolist()
    assert out[:4] == [1234.56, 1234.56, 1234.56, 12.5]
    assert np.isnan(out[4]) and np.isnan(out[5]) and out[6] == 3400.5


def test_demo_export_round_trip_across_dst(demo_data):
    readings, _ = demo_data
    raw = read_table(to_vendor_csv(readings).encode(), "export.csv")
    g = guess_mapping(raw)
    assert g["format"] == "Export demo (Prosumer Assistant)"
    hourly, rep = normalize(raw, g["mapping"], g["units"], g["kind"], g["label"], g["timezone"], g["dayfirst"], kwp=6)
    assert rep["gap_hours"] == 0 and rep["duplicates_removed"] == 0 and rep["dst_rows_dropped"] == 0
    assert len(hourly) == len(readings)
    assert (hourly["pv_kwh"] - readings["pv_kwh"]).abs().max() < 1e-3   # includes both DST switches


def _generic_export():
    idx = pd.date_range("2026-06-01", periods=96 * 3, freq="15min")
    power_w = np.clip(np.sin((np.asarray(idx.hour) + np.asarray(idx.minute) / 60 - 6) / 12 * np.pi), 0, None) * 4000
    return pd.DataFrame({
        "Time": idx.strftime("%Y-%m-%d %H:%M:%S"),
        "PV Power(W)": power_w.round(1),
        "Feed-in Energy(kWh)": np.cumsum(power_w / 4000 * 0.5).round(3),
        "Load consumption (W)": 500,
    }), power_w


def test_guess_power_and_cumulative_columns():
    df, power_w = _generic_export()
    raw = read_table(df.to_csv(index=False).encode(), "g.csv")
    g = guess_mapping(raw)
    assert g["mapping"] == {"timestamp": "Time", "grid_export": "Feed-in Energy(kWh)", "pv": "PV Power(W)",
                            "load": "Load consumption (W)"}
    assert g["units"]["pv"] == "W" and g["kind"]["grid_export"] == "cumulative" and g["kind"]["pv"] == "interval"
    hourly, rep = normalize(raw, g["mapping"], g["units"], g["kind"], "start", "Europe/Bucharest", True, kwp=5)
    assert rep["interval_minutes"] == 15
    assert hourly["pv_kwh"].sum() == pytest.approx(power_w.sum() / 1000 / 4, rel=1e-3)
    assert hourly["load_kwh"].sum() == pytest.approx(0.5 * 72, rel=1e-3)
    assert hourly["grid_export_kwh"].sum() == pytest.approx(df["Feed-in Energy(kWh)"].iloc[-1], rel=0.02)


def test_xlsx_and_json_inputs():
    df, _ = _generic_export()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        pd.DataFrame([["Raport invertor"], [""]]).to_excel(xw, index=False, header=False)
        df.to_excel(xw, index=False, startrow=3)
    raw = read_table(buf.getvalue(), "r.xlsx")
    assert "PV Power(W)" in raw.columns
    js = json.dumps({"data": df.head(20).to_dict(orient="records")}).encode()
    assert len(read_table(js, "r.json")) == 20


def test_unit_warning():
    df, _ = _generic_export()
    raw = read_table(df.to_csv(index=False).encode(), "g.csv")
    g = guess_mapping(raw)
    g["units"]["pv"] = "kW"             # wrong unit on purpose: values are W
    _, rep = normalize(raw, g["mapping"], g["units"], g["kind"], kwp=5)
    assert any("depășește" in w for w in rep["warnings"])
