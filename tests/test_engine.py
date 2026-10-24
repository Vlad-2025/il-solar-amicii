from datetime import date

import numpy as np
import pandas as pd
import pytest

from engine import calibrate, combine, load as loadmod, weather
from engine.solar import Site, physics
from ingest.demo import DEMO_SITE
from rules.compensation import load_rules, rule_for

SITE = Site.from_row(DEMO_SITE)


def test_clear_sky_june_day_is_plausible():
    idx = pd.date_range("2026-06-21", periods=24, freq="h", tz="UTC")
    w = weather.clear_sky_weather(SITE.lat, SITE.lon, idx, SITE.elevation)
    p = physics(SITE, w)
    assert 30 < p["pv_kw"].sum() < 45                      # 6 kWp, clear June day in Bucharest
    assert p["pv_kw"].max() <= SITE.inverter_kw + 1e-9     # clipped at the inverter
    night = p.index.tz_convert("Europe/Bucharest").hour.isin([0, 1, 2, 23])
    assert (p.loc[night, "pv_kw"] == 0).all()


def test_learned_correction_beats_both_baselines(demo_data):
    readings, w = demo_data
    model = calibrate.train(physics(SITE, w), readings["pv_kwh"], SITE.kwp)
    m = model.metrics
    assert m["mae_kwh_corrected"] < m["mae_kwh_physics"] < m["mae_kwh_persistence"]
    assert 0.6 < m["band_coverage"] < 0.95
    restored = calibrate.SolarCorrection.from_bytes(model.to_bytes())
    out = calibrate.apply(physics(SITE, w.iloc[-48:]), restored, SITE.inverter_kw)
    assert (out["pv_p10"] <= out["pv_p50"] + 1e-9).all() and (out["pv_p50"] <= out["pv_p90"] + 1e-9).all()


def test_too_little_history_is_refused(demo_data):
    readings, w = demo_data
    with pytest.raises(ValueError):
        calibrate.train(physics(SITE, w.iloc[:72]), readings["pv_kwh"].iloc[:72], SITE.kwp)


def test_load_model_and_recursive_forecast(demo_data):
    readings, w = demo_data
    lm = loadmod.train(readings["load_kwh"], w["temp_c"])
    assert lm.metrics["mae_kwh_model"] < lm.metrics["mae_kwh_baseline"]
    future = pd.date_range(readings.index[-1] + pd.Timedelta(hours=1), periods=168, freq="h", tz="UTC")
    fc = loadmod.forecast(lm, readings["load_kwh"], future, pd.Series(12.0, index=future))
    assert len(fc) == 168 and fc.notna().all() and (fc >= 0).all()
    assert fc.sum() == pytest.approx(readings["load_kwh"].iloc[-168:].sum(), rel=0.35)


def test_profile_sums_to_monthly():
    idx = pd.date_range(pd.Timestamp("2026-11-01", tz="Europe/Bucharest").tz_convert("UTC"), periods=24 * 30,
                        freq="h", tz="UTC")
    assert loadmod.profile(idx, 300).sum() == pytest.approx(300, rel=1e-6)


def test_battery_simulation_conserves_energy():
    idx = pd.date_range("2026-06-01", periods=72, freq="h", tz="UTC")
    rng = np.random.default_rng(1)
    pv = pd.Series(np.clip(np.sin((idx.hour - 4) / 16 * np.pi), 0, None) * 5, index=idx)
    load = pd.Series(rng.uniform(0.2, 1.5, len(idx)), index=idx)
    for cap in (0, 5):
        s = combine.simulate(pv, load, battery_kwh=cap)
        lhs = pv + s["imported"] + s["batt_discharge"]
        rhs = load + s["exported"] + s["batt_charge"]
        assert np.allclose(lhs, rhs)
        assert (s["soc_kwh"] <= cap + 1e-9).all()
    assert combine.simulate(pv, load, 5)["imported"].sum() < combine.simulate(pv, load, 0)["imported"].sum()


def test_month_estimate_combines_measured_forecast_and_rest(demo_data):
    readings, _ = demo_data
    idx = pd.date_range(readings.index[-1] + pd.Timedelta(hours=1), periods=168, freq="h", tz="UTC")
    sim = combine.simulate(pd.Series(0.5, index=idx), pd.Series(0.4, index=idx))
    rule = rule_for(date(2026, 10, 24), "individual", 6, load_rules())
    m = combine.month_estimate(date(2026, 10, 24), readings, sim, rule, 0.0, 1.3, 6)
    assert m["measured_days"] + m["forecast_days"] + m["extrapolated_days"] == pytest.approx(31, abs=0.05)
    assert m["billed_kwh"] == pytest.approx(max(0, m["consumed_kwh"] - m["delivered_kwh"]), abs=0.1)
    assert m["est_lei"] == pytest.approx(m["billed_kwh"] * 1.3, abs=0.01)
