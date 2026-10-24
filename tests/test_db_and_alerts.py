from datetime import date

import pandas as pd

from alerts import rules_publish
from db import repo
from rules.compensation import Rule, load_rules


def test_users_and_passwords(db):
    u = repo.create_user("Ana@Example.ro", "parola-sigura")
    assert u["email"] == "ana@example.ro" and u["plan"] == "free" and u["ntfy_topic"].startswith("prosumer-")
    assert repo.authenticate("ana@example.ro", "parola-sigura")["id"] == u["id"]
    assert repo.authenticate("ana@example.ro", "gresit") is None
    assert "parola" not in u["password_hash"]


def test_readings_round_trip_keeps_utc(db, demo_data):
    u = repo.create_user("readings@example.ro", "x" * 10)
    site = repo.upsert_site(u["id"], {"lat": 45.0, "lon": 25.0, "kwp": 5, "tilt": 30, "azimuth": 180})
    readings, _ = demo_data
    part = readings.iloc[:500]
    assert repo.save_readings(site["id"], part) == 500
    back = repo.load_readings(site["id"])
    assert back.index.tz is not None and back.index[0] == part.index[0]
    assert (back["pv_kwh"] - part["pv_kwh"]).abs().max() < 1e-9
    repo.save_readings(site["id"], part.iloc[100:200])             # re-import replaces, no duplicates
    assert len(repo.load_readings(site["id"])) == 500
    s = repo.readings_summary(site["id"])
    assert s["rows"] == 500 and s["has_load"] and s["start"] == part.index[0]


def test_bill_save_and_load(db):
    u = repo.create_user("bills@example.ro", "x" * 10)
    site = repo.upsert_site(u["id"], {"lat": 45.0, "lon": 25.0, "kwp": 5, "tilt": 30, "azimuth": 180})
    bid = repo.save_bill(site["id"], {"supplier": "Hidroelectrica", "period_start": date(2026, 9, 1),
                                      "period_end": date(2026, 9, 30), "total_lei": 100.5, "status": "confirmed"},
                         [{"line_type": "total", "amount_lei": 100.5, "confidence": 0.9, "user_confirmed": True}])
    b = repo.get_bill(bid)
    assert b["period_end"] == date(2026, 9, 30) and b["lines"][0]["amount_lei"] == 100.5
    repo.save_checks(bid, [{"check_type": "x", "severity": "ok", "message": "m"}])
    assert repo.get_checks(bid)[0]["severity"] == "ok"
    repo.delete_bill(bid)
    assert repo.get_bill(bid) is None


def test_new_rule_version_notifies_affected_users(db, monkeypatch):
    sent = []
    monkeypatch.setattr(rules_publish.ntfy, "send", lambda topic, title, msg, **kw: sent.append((topic, msg)) or True)
    for r in load_rules():                                     # existing versions, silently
        repo.upsert_rule(r.to_dict())
    u = repo.create_user("company@example.ro", "x" * 10)
    repo.upsert_site(u["id"], {"lat": 45.0, "lon": 25.0, "kwp": 300, "tilt": 30, "azimuth": 180,
                               "customer_type": "company"})
    new = Rule.from_dict({
        "id": "test-v9", "version": 9, "effective_from": "2027-01-01", "title": "Test: limită 500 kW",
        "applies_to": {"customer_types": ["company"], "max_kw": 500},
        "params": {"compensation_type": "quantity", "netting_period": "month", "quantity_compensation_max_kw": 500,
                   "quantity_compensation_until": "2030-12-31"},
        "summary_ro": "test"})
    res = rules_publish.publish(new)
    assert res["new"]
    company = [s for s in sent if "400 kW → 500 kW" in s[1]]
    assert company, sent
    notes = repo.list_notifications(u["id"])
    assert notes and notes[0]["delivered"] and notes[0]["payload_json"]["rule_id"] == "test-v9"
    assert not rules_publish.publish(new)["notified"]          # re-publishing doesn't page again


def test_simulated_demo_rule_is_not_published(db, monkeypatch):
    monkeypatch.setattr(rules_publish.ntfy, "send", lambda *a, **k: False)
    from rules.compensation import STAGED_DIR, load_rule_file
    u = repo.create_user("sim@example.ro", "x" * 10)
    site = repo.upsert_site(u["id"], {"lat": 45.0, "lon": 25.0, "kwp": 6, "tilt": 30, "azimuth": 180})
    res = rules_publish.simulate_for_user(load_rule_file(STAGED_DIR / "demo_next_version.yaml"), repo.get_user(u["id"]), site)
    assert res["title"].startswith("[DEMO]")
    assert "ro-compensare-v3-DEMO" not in [r["id"] for r in repo.list_rules()]
    assert repo.list_notifications(u["id"])[0]["payload_json"]["simulated"]


def test_forecast_rows(db):
    u = repo.create_user("fc@example.ro", "x" * 10)
    site = repo.upsert_site(u["id"], {"lat": 45.0, "lon": 25.0, "kwp": 6, "tilt": 30, "azimuth": 180})
    idx = pd.date_range("2026-10-24", periods=3, freq="h", tz="UTC")
    df = pd.DataFrame({"pv_p50": [0, 1, 2.5], "load_p50": [0.3, 0.4, 0.5]}, index=idx)
    repo.save_forecast(site["id"], df, "v1")
    run_at, back, version = repo.load_latest_forecast(site["id"])
    assert version == "v1" and back["pv_p50"].tolist() == [0, 1, 2.5] and back.index[0] == idx[0]
