"""External services with fake responses in the shape their APIs return (no network)."""
from types import SimpleNamespace

import pandas as pd
import pytest

from alerts import ntfy
from billing import stripe_checkout as sc
from engine import pvgis, weather
from engine.solar import Site


class FakeResp:
    def __init__(self, payload, ok=True):
        self._p, self.ok = payload, ok

    def raise_for_status(self):
        if not self.ok:
            import requests
            raise requests.HTTPError("boom")

    def json(self):
        return self._p


def test_open_meteo_is_shifted_to_start_of_hour(monkeypatch):
    payload = {"hourly": {
        "time": ["2026-10-24T10:00", "2026-10-24T11:00"],
        "shortwave_radiation": [300.0, 400.0], "direct_normal_irradiance": [500.0, 600.0],
        "diffuse_radiation": [100.0, 120.0], "temperature_2m": [15.0, 16.0], "wind_speed_10m": [2.0, 3.0],
        "cloud_cover": [20.0, 10.0]}}
    seen = {}
    monkeypatch.setattr(weather.requests, "get", lambda url, params, timeout: seen.update(params) or FakeResp(payload))
    df = weather.fetch_forecast(44.4, 26.1, days=7)
    assert df.index[0] == pd.Timestamp("2026-10-24 09:00", tz="UTC")       # value for 09:00–10:00
    assert df.loc[df.index[1], "ghi"] == 400 and list(df.columns) == weather.COLUMNS
    assert seen["timezone"] == "UTC" and seen["wind_speed_unit"] == "ms"


def test_open_meteo_failure_falls_back_to_clear_sky(monkeypatch):
    import requests

    from engine import pipeline

    def boom(*a, **k):
        raise requests.ConnectionError("offline")
    monkeypatch.setattr(weather.requests, "get", boom)
    w, source = pipeline.forecast_weather({"lat": 44.4, "lon": 26.1, "elevation": 80}, days=2)
    assert "indisponibil" in source and len(w) == 48 and w["ghi"].max() > 0


def test_pvgis_parse_and_aspect(monkeypatch):
    payload = {"outputs": {"monthly": {"fixed": [{"month": m, "E_m": 100.0 + m} for m in range(1, 13)]},
                           "totals": {"fixed": {"E_y": 7800.0}}}}
    seen = {}
    monkeypatch.setattr(pvgis.requests, "get", lambda url, params, timeout: seen.update(params) or FakeResp(payload))
    out = pvgis.fetch(Site(lat=44.4, lon=26.1, kwp=6, tilt=30, azimuth=135))
    assert out["annual_kwh"] == 7800 and out["monthly_kwh"][12] == 112
    assert seen["aspect"] == -45                                            # south-east in PVGIS terms


def test_pvgis_compare_flags_underperformance():
    idx = pd.date_range(pd.Timestamp("2026-06-01", tz="Europe/Bucharest").tz_convert("UTC"), periods=24 * 30, freq="h", tz="UTC")
    pv = pd.Series(0.5, index=idx)                                          # 360 kWh in June
    res = pvgis.compare(pv, {6: 800.0})
    assert res["ratio"] == pytest.approx(0.45) and "sub" in res["message"]


def test_ntfy_posts_json_with_diacritics(monkeypatch):
    sent = {}
    monkeypatch.setattr(ntfy.requests, "post", lambda url, json, headers, timeout: sent.update(url=url, json=json) or FakeResp({}))
    assert ntfy.send("prosumer-abc", "Legea s-a schimbat", "Țară, ș și ț", tags=["zap"])
    assert sent["json"]["topic"] == "prosumer-abc" and "ș" in sent["json"]["message"]
    assert not ntfy.send(None, "x", "y")


def test_stripe_refuses_live_keys(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_123")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_1")
    assert not sc.configured()
    with pytest.raises(sc.StripeNotConfigured):
        sc.create_checkout("a@b.ro", 1, "https://app", "tok")


def test_stripe_checkout_and_verify(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_1")
    created = {}

    class Sessions:
        def create(self, params):
            created.update(params)
            return SimpleNamespace(url="https://checkout.stripe.com/c/pay/cs_test_1")

        def retrieve(self, sid, params):
            sub = {"items": {"data": [{"current_period_end": 1798761600}]}}
            return SimpleNamespace(status="complete", client_reference_id="7", customer="cus_1", subscription=sub)

    fake = SimpleNamespace(v1=SimpleNamespace(checkout=SimpleNamespace(sessions=Sessions())))
    monkeypatch.setattr(sc, "_client", lambda: fake)
    url = sc.create_checkout("a@b.ro", 7, "https://app.example/", "tok123")
    assert url.startswith("https://checkout.stripe.com")
    assert created["mode"] == "subscription" and created["client_reference_id"] == "7"
    assert created["success_url"] == "https://app.example/abonament?session_id={CHECKOUT_SESSION_ID}&u=tok123"
    ok = sc.verify_session("cs_test_1", 7)
    assert ok["ok"] and ok["customer"] == "cus_1" and ok["period_end"].year == 2027
    assert not sc.verify_session("cs_test_1", 8)["ok"]                     # someone else's session


def test_login_token_round_trip(monkeypatch):
    monkeypatch.setenv("APP_SECRET", "s3cret")
    from app import common
    tok = common.sign_login(42)
    assert common.verify_login(tok) == 42
    assert common.verify_login(tok[:-1] + ("0" if tok[-1] != "0" else "1")) is None
    assert common.verify_login(common.sign_login(42, ttl_s=-1)) is None
