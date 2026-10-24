from datetime import date

import numpy as np
import pandas as pd
import pytest

from engine import devices, planner, profiles
from engine.demand import baseline, year_index

INDEX = year_index(date(2026, 10, 24))
NO_PANELS = {"id": 1, "lat": 46.77, "lon": 23.59, "elevation": 350, "kwp": 0, "tilt": 30, "azimuth": 180,
             "battery_kwh": 0, "customer_type": "individual", "price_lei_kwh": 1.25, "monthly_kwh": None}


@pytest.fixture(autouse=True)
def offline_weather(monkeypatch):
    """Deterministic weather for the planning year (the real code fetches Open-Meteo)."""
    from engine import pipeline
    from ingest.demo import synthetic_weather

    def fake(site, start, end):
        idx = pd.date_range(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1),
                            freq="h", inclusive="left", tz="UTC")
        return synthetic_weather(site["lat"], site["lon"], idx, site.get("elevation") or 0)
    monkeypatch.setattr(pipeline, "historical_weather", fake)


def test_psc_profiles_are_complete_and_seasonal():
    for area in ("urban", "rural"):
        h = profiles.hourly_shapes(area)
        assert h.shape == (24, 4) and np.allclose(h.sum(), 1.0)
        assert h["working_cold"].idxmax() in (18, 19, 20) and h["working_warm"].idxmax() in (19, 20, 21)
    year = profiles.default_profile(INDEX, 3000, "urban")
    assert year.sum() == pytest.approx(3000, rel=1e-6)
    day, night = (profiles.default_profile(INDEX, 3000, "urban", u) for u in ("day", "night"))
    noon = INDEX.tz_convert("Europe/Bucharest").hour.isin(range(9, 16))
    assert day[noon].sum() > year[noon].sum() > night[noon].sum()


def test_baseline_cascade():
    # nothing known -> labelled assumption
    s, info = baseline(INDEX, NO_PANELS, {}, None, [], [], None)
    assert info["source"] == "assumption" and info["annual_kwh"] == pytest.approx(2400, rel=0.01)
    # profile value
    s, info = baseline(INDEX, {**NO_PANELS, "monthly_kwh": 300}, {}, None, [], [], None)
    assert info["source"] == "profile" and s.sum() == pytest.approx(3600, rel=1e-3)
    # bills only count for households without panels
    bill = {"period_start": date(2026, 9, 1), "period_end": date(2026, 9, 30),
            "lines": [{"line_type": "energy_consumed", "qty_kwh": 250}]}
    _, info = baseline(INDEX, NO_PANELS, {}, None, [bill], [], None)
    assert info["source"] == "bills" and info["annual_kwh"] == pytest.approx(250 / 30 * 365, rel=0.01)
    _, info = baseline(INDEX, {**NO_PANELS, "kwp": 5}, {}, None, [bill], [], None)
    assert info["source"] == "assumption" and any("prosumator" in n for n in info["notes"])
    # manual annual beats bills
    _, info = baseline(INDEX, NO_PANELS, {"annual_kwh": 5000}, None, [bill], [], None)
    assert info["source"] == "manual"


def test_baseline_personal(demo_data):
    readings, _ = demo_data
    idx = year_index(date(2026, 10, 23))
    s, info = baseline(idx, NO_PANELS, {}, readings, [], [], None)
    assert info["source"] == "personal_full" and s.sum() == pytest.approx(readings["load_kwh"].reindex(idx).sum(), rel=0.01)
    few = readings.loc[readings.index >= idx[-1] - pd.Timedelta(days=40)]
    s, info = baseline(idx, NO_PANELS, {}, few, [], [], None)
    assert info["source"] == "personal_partial" and info["days_of_data"] >= 40
    assert 0.5 < s.sum() / readings["load_kwh"].reindex(idx).sum() < 1.5


def test_devices_energy():
    ev = {"name": "EV", "kind": "ev", "power_w": 7400, "start_hour": 19, "days_per_week": 7, "ev_km_day": 40,
          "ev_kwh_100km": 18}
    s = devices.device_load(ev, INDEX)
    assert s.sum() == pytest.approx(40 * 18 / 100 / 0.9 * 365, rel=0.01)
    assert s.max() <= 7.4 + 1e-9
    washer = {"name": "W", "kind": "schedule", "power_w": 2000, "hours_per_day": 1.5, "start_hour": 23, "days_per_week": 5}
    s = devices.device_load(washer, INDEX)
    weeks = 365 / 7
    assert s.sum() == pytest.approx(3.0 * 5 * weeks, rel=0.03)
    hp = {"name": "HP", "kind": "heating", "annual_kwh": 4000}
    temp = pd.Series(np.where(INDEX.month.isin([12, 1, 2]), -2.0, 20.0), index=INDEX)
    s = devices.device_load(hp, INDEX, temp)
    assert s.sum() == pytest.approx(4000, rel=1e-6) and s[INDEX.month == 7].sum() == 0
    pool = {"name": "P", "kind": "schedule", "power_w": 750, "hours_per_day": 8, "months": [6, 7, 8]}
    assert devices.device_load(pool, INDEX)[INDEX.month == 1].sum() == 0


def test_batch_simulation_matches_single():
    rng = np.random.default_rng(3)
    pv1 = np.clip(np.sin(np.arange(500) / 24 * 2 * np.pi), 0, None)
    load = rng.uniform(0.1, 1.2, 500)
    kwps, caps = np.array([0, 2, 4, 4]), np.array([0, 0, 5, 10])
    b, s, d = planner.simulate_batch(pv1, load, kwps.astype(float), caps.astype(float))
    for i in range(4):
        e = planner.evaluate(pv1, load, float(kwps[i]), float(caps[i]))
        assert b[i] == pytest.approx(e.bought) and s[i] == pytest.approx(e.sold) and d[i] == pytest.approx(e.discharged)


def test_plan_without_panels_obeys_both_rules():
    p = planner.plan(NO_PANELS, {"annual_kwh": 3500}, [], None, [], index=INDEX)
    rec, alt = p["recommended"], {a["label"]: a for a in p["alternatives"]}
    assert rec["panels_total"] > 0 and rec["exchange_kwh"] < p["current"]["exchange_kwh"]
    if "Cu un panou în plus" in alt:                    # one more panel must not help
        assert alt["Cu un panou în plus"]["exchange_kwh"] >= rec["exchange_kwh"] - 1 or rec["panels_total"] == 30
    if rec["battery_modules_total"]:
        assert rec["battery_cycles"] >= 150
        less = alt["Cu o baterie mai puțin"]
        assert less["exchange_kwh"] > rec["exchange_kwh"]
    assert p["costs"]["gross_lei"] > 0 and set(p["payback"]["scenarios"]) == {"current", "partial", "none"}
    assert p["baseline"]["source"] == "manual" and p["limits"]


def test_flexible_devices_get_moved_into_sunshine():
    ev = {"id": 7, "name": "EV", "kind": "ev", "power_w": 7400, "start_hour": 19, "days_per_week": 7,
          "ev_km_day": 30, "ev_kwh_100km": 17, "flexible": True}
    site = {**NO_PANELS, "kwp": 6, "battery_kwh": 0}
    p = planner.plan(site, {"annual_kwh": 3000, "max_panels": 14, "max_battery_modules": 0}, [ev], None, [], index=INDEX)
    tip = p["schedule_tips"][0]
    assert tip["id"] == 7 and 9 <= tip["to_hour"] <= 15 and tip["gain_kwh"] > 100
    assert p["recommended"]["battery_modules_total"] == 0      # limit respected


def test_owner_keeps_system_and_battery_money_is_honest(demo_data):
    readings, _ = demo_data
    from ingest.demo import DEMO_SITE
    idx = year_index(date(2026, 10, 23))
    p = planner.plan({**DEMO_SITE, "id": 2}, {"existing_cost_lei": 30000, "existing_year": 2025}, [], readings, [], index=idx)
    assert p["recommended"]["kwp"] >= 6.0 and p["recommended"]["battery_kwh"] >= 5.0
    if p["recommended"]["battery_modules_added"]:
        scen = p["payback"]["scenarios"]
        # under monthly quantity compensation a battery saves (almost) nothing before 2030
        assert scen["current"]["saving_year1_lei"] < 200
        assert scen["none"]["saving_after_2030_lei"] > scen["current"]["saving_after_2030_lei"]
    assert p["existing_payback"]["payback_years"]["current"] is not None
