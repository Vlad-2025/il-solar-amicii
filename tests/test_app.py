"""Headless smoke test of the Streamlit app: demo login, premium unlock, every page, bill confirm."""
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app" / "Home.py")
PAGES = ["acasa", "facturi", "prognoza", "plan", "date_invertor", "reguli", "abonament", "profil"]


def _click(at, label):
    btn = [b for b in at.button if b.label == label]
    assert btn, f"button {label!r} not found in {[b.label for b in at.button]}"
    btn[0].click().run()


def _no_errors(at, where):
    assert not at.exception, f"{where}: {[e.value for e in at.exception]}"


@pytest.fixture(scope="module")
def app():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    _no_errors(at, "login page")
    from db import repo
    from db.seed import DEMO_EMAIL
    repo.update_user(repo.get_user_by_email(DEMO_EMAIL)["id"], plan="free")   # other tests may have unlocked it
    _click(at, "Intră în contul demo")
    return at


def test_all_pages_render_free_then_premium(app):
    for p in PAGES:
        app.switch_page(f"pages/{p}.py").run()
        _no_errors(app, f"{p} (free)")
    app.switch_page("pages/abonament.py").run()
    _click(app, "Activează Premium pentru demo (fără Stripe)")
    for p in PAGES:
        app.switch_page(f"pages/{p}.py").run()
        _no_errors(app, f"{p} (premium)")
    app.switch_page("pages/prognoza.py").run()
    assert {m.label for m in app.metric} >= {"Consum din rețea", "Livrat în rețea", "Compensat"}


def test_bill_confirm_and_check(app):
    from bills.parse import parse_bill
    app.switch_page("pages/facturi.py").run()
    app.session_state["draft"] = parse_bill((ROOT / "data/demo/factura_demo_2026-09.pdf").read_bytes(), "f.pdf")
    app.session_state["draft_key"] = "test"
    app.run()
    _click(app, "Confirmă și salvează")
    _no_errors(app, "bill confirm")
    # Demo inverter data is regenerated up to yesterday, so the exact gap drifts by a few tenths.
    flagged = [w.value for w in app.warning if "Energia livrată" in w.value]
    assert flagged and any(re.search(r"-1[01],\d%", v) for v in flagged), flagged
    assert any(t.value.startswith("Către: Furnizor Demo SA") for t in app.text_area)


def test_charts_are_valid_vega_lite(demo_data):
    from app import common
    readings, _ = demo_data
    idx = readings.index[-48:]
    hourly = pd.DataFrame({"pv_p10": 0.8, "pv_p50": 1.0, "pv_p90": 1.2, "load_p50": 0.5}, index=idx)
    common.hourly_chart(hourly).to_dict()                      # raises on an invalid spec
    daily = pd.DataFrame({"pv": [20, 18], "load": [10, 9]},
                         index=pd.date_range("2026-10-25", periods=2, tz="Europe/Bucharest"))
    common.daily_bars(daily, {"pv": "Producție", "load": "Consum"}).to_dict()
