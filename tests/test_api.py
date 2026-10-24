"""Mobile API end to end with FastAPI's TestClient (lifespan seeds the demo account)."""
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api import auth  # noqa: E402
from api.main import app  # noqa: E402

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"
SITE = {"lat": 45.75, "lon": 21.23, "kwp": 8.0, "tilt": 25, "azimuth": 180, "battery_kwh": 0, "price_lei_kwh": 1.2}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def demo(client):
    r = client.post("/auth/demo")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_auth_required(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers=_h("garbage.token")).status_code == 401


def test_new_user_onboarding_and_free_tier(client):
    r = client.post("/auth/register", json={"email": "maria@example.ro", "password": "parola-buna"})
    assert r.status_code == 200 and r.json()["needs_onboarding"]
    tok = r.json()["token"]
    assert client.post("/auth/register", json={"email": "maria@example.ro", "password": "parola-buna"}).status_code == 409
    assert client.post("/auth/login", json={"email": "maria@example.ro", "password": "gresit123"}).status_code == 401
    assert client.get("/forecast/summary", headers=_h(tok)).status_code == 409          # no site yet
    me = client.put("/site", json=SITE, headers=_h(tok)).json()
    assert not me["needs_onboarding"] and me["site"]["inverter_kw"] == 8.0
    assert me["ntfy"]["app_url"].startswith("ntfy://")
    s = client.get("/forecast/summary", headers=_h(tok)).json()
    assert len(s["daily"]) >= 7 and sum(d["pv"] for d in s["daily"]) > 0
    r = client.get("/forecast", headers=_h(tok))
    assert r.status_code == 402 and "Premium" in r.json()["detail"]
    assert client.put("/site", json={**SITE, "lat": 60}, headers=_h(tok)).status_code == 422


def test_bill_upload_confirm_and_checks(client, demo):
    assert client.post("/subscription/demo-unlock", headers=_h(demo)).json()["user"]["premium"]
    with open(DEMO / "factura_demo_2026-09.pdf", "rb") as f:
        r = client.post("/bills", files={"file": ("factura.pdf", f, "application/pdf")}, headers=_h(demo))
    assert r.status_code == 200, r.text
    draft = r.json()
    assert draft["status"] == "draft" and draft["total_lei"] == 7.62 and len(draft["lines"]) == 14
    assert all(v["ok"] for v in draft["validation"]) and draft["checks"] is None
    assert all(ln["explanation"] for ln in draft["lines"])

    lines = [{k: ln[k] for k in ("line_type", "label_raw", "qty_kwh", "unit_price", "amount_lei")} for ln in draft["lines"]]
    done = client.post(f"/bills/{draft['id']}/confirm", json={"lines": lines}, headers=_h(demo)).json()
    assert done["status"] == "confirmed"
    flagged = [c for c in done["checks"] if c["severity"] == "worth_checking"]
    assert flagged and flagged[0]["check_type"] == "delivered_vs_inverter"
    assert done["complaint"]["body"].startswith("Către: Furnizor Demo SA")
    assert done["why_pay"]

    stricter = client.post(f"/bills/{draft['id']}/check", json={"threshold_pct": 50}, headers=_h(demo)).json()
    assert not [c for c in stricter["checks"] if c["severity"] == "worth_checking"]
    listed = client.get("/bills", headers=_h(demo)).json()
    assert any(b["id"] == draft["id"] for b in listed)
    assert client.delete(f"/bills/{draft['id']}", headers=_h(demo)).status_code == 200
    assert client.get(f"/bills/{draft['id']}", headers=_h(demo)).status_code == 404


def test_forecast_premium(client, demo):
    client.post("/subscription/demo-unlock", headers=_h(demo))
    fc = client.get("/forecast", headers=_h(demo)).json()
    assert len(fc["hourly"]) == 168 and {"pv_p50", "pv_p10", "load_p50"} <= set(fc["hourly"][0])
    assert fc["hourly"][0]["ts"].endswith(("+02:00", "+03:00"))        # Romanian local time
    assert fc["month"]["rule_id"] and fc["solar_metrics"]["nmae_pct_corrected"] < fc["solar_metrics"]["nmae_pct_physics"]


def test_alerts_and_demo_rule(client, demo):
    a = client.get("/alerts", headers=_h(demo)).json()
    assert a["current_rule"]["version"] == 2 and a["change"]["impact"]
    r = client.post("/alerts/demo", headers=_h(demo)).json()
    assert r["title"].startswith("[DEMO]")
    assert client.get("/alerts", headers=_h(demo)).json()["notifications"][0]["simulated"]


def test_readings_upload_demo_export(client):
    tok = client.post("/auth/register", json={"email": "csv@example.ro", "password": "parola-buna"}).json()["token"]
    client.put("/site", json=SITE, headers=_h(tok))
    with open(DEMO / "demo_inverter_export.csv", "rb") as f:
        r = client.post("/readings", files={"file": ("export.csv", f, "text/csv")}, headers=_h(tok))
    assert r.status_code == 200, r.text
    assert r.json()["format"] and r.json()["hours"] > 9000
    bad = client.post("/readings", files={"file": ("x.csv", b"a;b\n1;2\n3;4\n", "text/csv")}, headers=_h(tok))
    assert bad.status_code == 422 and "columns" in bad.json()["detail"]


def test_checkout_guards_and_stripe_return(client, monkeypatch):
    tok = client.post("/auth/register", json={"email": "pay@example.ro", "password": "parola-buna"}).json()
    uid, tok = tok["user"]["id"], tok["token"]
    assert client.post("/subscription/checkout", json={"return_url": "https://evil.example"}, headers=_h(tok)).status_code == 422
    assert client.post("/subscription/checkout", json={"return_url": "prosumer://cont"}, headers=_h(tok)).status_code == 409
    assert client.post("/subscription/demo-unlock", headers=_h(tok)).status_code == 403

    from billing import stripe_checkout as sc
    monkeypatch.setattr(sc, "verify_session", lambda sid, u: {"ok": u == uid, "customer": "cus_1", "period_end": None})
    state = auth.sign(uid, ttl_s=600, purpose="stripe")
    r = client.get("/stripe/return", params={"session_id": "cs_test_9", "s": state, "r": "prosumer://cont"},
                   follow_redirects=False)
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert loc.scheme == "prosumer" and parse_qs(loc.query)["status"] == ["ok"]
    assert client.get("/me", headers=_h(tok)).json()["user"]["premium"]
    r = client.get("/stripe/return", params={"session_id": "cs_test_9", "s": auth.sign(uid), "r": "prosumer://cont"},
                   follow_redirects=False)                                           # api token is not a stripe state
    assert "status=failed" in r.headers["location"]
    r = client.get("/stripe/return", params={"s": state, "r": "https://evil.example"}, follow_redirects=False)
    assert r.status_code == 422


def test_planner_flow_without_panels(client):
    tok = client.post("/auth/register", json={"email": "plan@example.ro", "password": "parola-buna"}).json()["token"]
    me = client.put("/site", json={**SITE, "kwp": 0}, headers=_h(tok)).json()
    assert me["site"]["kwp"] == 0 and me["site"]["inverter_kw"] is None
    cat = client.get("/plan/catalog", headers=_h(tok)).json()
    assert {"catalog", "kinds", "usage_types", "areas", "defaults", "scenarios"} <= set(cat)
    ev = next(c for c in cat["catalog"] if c["key"] == "ev")
    r = client.post("/devices", json={k: v for k, v in ev.items() if k != "key"}, headers=_h(tok))
    assert r.status_code == 200, r.text
    dev = r.json()
    assert dev["months"] == list(range(1, 13)) and dev["flexible"]
    assert client.post("/devices", json={"name": "X", "kind": "rocket"}, headers=_h(tok)).status_code == 422
    edited = client.put(f"/devices/{dev['id']}", json={**{k: v for k, v in ev.items() if k != "key"}, "ev_km_day": 60},
                        headers=_h(tok)).json()
    assert edited["ev_km_day"] == 60
    st = client.put("/plan/settings", json={"annual_kwh": 3200, "area": "rural", "bogus": 1}, headers=_h(tok)).json()
    assert st["annual_kwh"] == 3200 and st["area"] == "rural" and "bogus" not in st and st["panel_wp"] == 450
    plan = client.post("/plan", headers=_h(tok)).json()
    assert plan["baseline"]["source"] == "manual" and plan["devices"][0]["annual_kwh"] > 1000
    assert plan["recommended"]["panels_total"] > 0 and plan["costs"]["gross_lei"] > 0
    assert {"current", "partial", "none"} == set(plan["payback"]["scenarios"])
    assert plan["alternatives"][0]["label"] == "Fără panouri"
    assert client.delete(f"/devices/{dev['id']}", headers=_h(tok)).status_code == 200
    assert client.get("/devices", headers=_h(tok)).json() == []


def test_planner_demo_owner(client, demo):
    plan = client.post("/plan", headers=_h(demo)).json()
    assert plan["baseline"]["source"] == "personal_full"
    assert plan["recommended"]["kwp"] >= plan["current"]["kwp"]
    assert plan["current"]["panels"] > 0
