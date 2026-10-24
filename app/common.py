"""Shared app plumbing: secrets, bootstrap, login state, premium gate, formatting, charts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from db import repo
from rules.explain import _n

PREMIUM_PAGES_NOTE = "Verificarea facturii, prognoza și istoricul sunt incluse în abonamentul Premium."
LOCAL_TZ = "Europe/Bucharest"
ROOT = Path(__file__).resolve().parents[1]


def repo_path(rel: str) -> Path:
    return ROOT / rel


# ---------------------------------------------------------------- secrets and bootstrap
def secrets_to_env() -> None:
    """Streamlit secrets -> environment, so engine/db/jobs code reads one place (os.environ)."""
    try:
        for k, v in st.secrets.items():
            if isinstance(v, (str, int, float, bool)) and k not in os.environ:
                os.environ[k] = str(v)
    except Exception:  # noqa: BLE001 - no secrets.toml is fine locally
        pass


@st.cache_resource(show_spinner="Pregătim aplicația (prima pornire durează ~30 s)...")
def bootstrap() -> dict:
    from db.client import init_db
    from db.seed import ensure_admin, seed_demo

    init_db()
    ensure_admin()
    try:
        return seed_demo()
    except Exception as exc:  # noqa: BLE001 - the app must start even if the demo can't be built
        return {"status": "error", "error": str(exc)}


# ---------------------------------------------------------------- login
def _secret() -> bytes:
    return (os.environ.get("APP_SECRET") or os.environ.get("DATABASE_URL") or "dev-secret-change-me").encode()


def sign_login(user_id: int, ttl_s: int = 3600) -> str:
    """Short-lived token so the Stripe redirect (a fresh browser session) can log the user back in."""
    exp = int(time.time()) + ttl_s
    msg = f"{user_id}:{exp}".encode()
    sig = hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32]
    return base64.urlsafe_b64encode(msg).decode().rstrip("=") + "." + sig


def verify_login(token: str) -> int | None:
    try:
        body, sig = token.split(".")
        msg = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        if not hmac.compare_digest(hmac.new(_secret(), msg, hashlib.sha256).hexdigest()[:32], sig):
            return None
        uid, exp = msg.decode().split(":")
        return int(uid) if int(exp) >= time.time() else None
    except Exception:  # noqa: BLE001
        return None


def login(user: dict) -> None:
    st.session_state["user_id"] = user["id"]


def logout() -> None:
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def user() -> dict | None:
    uid = st.session_state.get("user_id")
    return repo.get_user(uid) if uid else None


def site() -> dict | None:
    u = user()
    return repo.get_site_for_user(u["id"]) if u else None


def is_premium(u: dict | None = None) -> bool:
    u = u or user()
    return bool(u and u.get("plan") == "premium")


def require_site() -> dict:
    s = site()
    if not s:
        st.info("Completați mai întâi profilul instalației (locație, kWp, înclinare, orientare).")
        st.page_link("pages/profil.py", label="Mergi la Profil", icon=":material/solar_power:")
        st.stop()
    return s


def require_premium(feature: str) -> None:
    if is_premium():
        return
    st.info(f"**{feature}** face parte din abonamentul Premium. {PREMIUM_PAGES_NOTE}", icon=":material/lock:")
    st.page_link("pages/abonament.py", label="Vezi abonamentul (mod de test, fără bani reali)",
                 icon=":material/workspace_premium:")
    st.stop()


def app_url() -> str:
    url = os.environ.get("APP_URL")
    if url:
        return url.rstrip("/")
    ctx_url = getattr(st.context, "url", None)
    if ctx_url:
        from urllib.parse import urlsplit
        p = urlsplit(ctx_url)
        return f"{p.scheme}://{p.netloc}"
    return "http://localhost:8501"


# ---------------------------------------------------------------- forecast (cached 1 hour)
SITE_KEY_FIELDS = ("lat", "lon", "kwp", "tilt", "azimuth", "inverter_kw", "battery_kwh", "customer_type",
                   "price_lei_kwh", "monthly_kwh", "carryover_kwh")


@st.cache_data(ttl=3600, show_spinner="Calculăm prognoza...")
def _forecast_cached(site_id: int, site_key: tuple, models_key: tuple, hour: str) -> dict:
    from engine.pipeline import run_forecast

    return run_forecast(repo.get_site(site_id), save=True)


def forecast(site_row: dict, force: bool = False) -> dict:
    models_key = tuple(str((repo.load_model(site_row["id"], k) or {}).get("trained_at")) for k in ("solar", "load"))
    site_key = tuple(site_row.get(k) for k in SITE_KEY_FIELDS)
    if force:
        _forecast_cached.clear()
    hour = pd.Timestamp.now(tz="UTC").floor("h").isoformat()
    return _forecast_cached(site_row["id"], site_key, models_key, hour)


# ---------------------------------------------------------------- formatting
def num(x, d: int = 0) -> str:
    return _n(x, d)


def kwh(x, d: int = 0) -> str:
    return f"{_n(x, d)} kWh"


def lei(x) -> str:
    return f"{_n(x, 2)} lei"


MONTHS = ["", "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
          "septembrie", "octombrie", "noiembrie", "decembrie"]
DAYS = ["Lun", "Mar", "Mie", "Joi", "Vin", "Sâm", "Dum"]


def month_name(d: date) -> str:
    return f"{MONTHS[d.month]} {d.year}"


def day_label(ts: pd.Timestamp) -> str:
    return f"{DAYS[ts.weekday()]} {ts.day:02d}.{ts.month:02d}"


def local(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = out.index.tz_convert(LOCAL_TZ)
    return out


# ---------------------------------------------------------------- charts
PV_COLOR, LOAD_COLOR, BAND_COLOR = "#e8a317", "#2f6db5", "#f5d38a"


def hourly_chart(hourly: pd.DataFrame, show_load: bool = True) -> alt.Chart:
    d = local(hourly).reset_index().rename(columns={"index": "ts"})
    d["ts"] = d["ts"].dt.tz_localize(None)
    base = alt.Chart(d).encode(x=alt.X("ts:T", title=None, axis=alt.Axis(format="%a %d", labelAngle=0)))
    layers = []
    if d["pv_p10"].notna().any():
        layers.append(base.mark_area(color=BAND_COLOR, opacity=0.55).encode(
            y=alt.Y("pv_p10:Q", title="kWh pe oră"), y2="pv_p90:Q",
            tooltip=[alt.Tooltip("ts:T", title="Ora", format="%d.%m %H:%M"),
                     alt.Tooltip("pv_p10:Q", title="Producție P10", format=".2f"),
                     alt.Tooltip("pv_p90:Q", title="Producție P90", format=".2f")]))
    layers.append(base.mark_line(color=PV_COLOR, strokeWidth=2).encode(
        y=alt.Y("pv_p50:Q", title="kWh pe oră"),
        tooltip=[alt.Tooltip("ts:T", title="Ora", format="%d.%m %H:%M"),
                 alt.Tooltip("pv_p50:Q", title="Producție", format=".2f")]))
    if show_load and "load_p50" in d:
        layers.append(base.mark_line(color=LOAD_COLOR, strokeWidth=1.5, strokeDash=[4, 3]).encode(
            y="load_p50:Q", tooltip=[alt.Tooltip("ts:T", title="Ora", format="%d.%m %H:%M"),
                                     alt.Tooltip("load_p50:Q", title="Consum", format=".2f")]))
    return alt.layer(*layers).properties(height=300)


def daily_bars(daily: pd.DataFrame, cols: dict[str, str]) -> alt.Chart:
    """cols: column -> Romanian label. Grouped bars per day."""
    d = daily[list(cols)].copy()
    d["zi"] = [day_label(ts) for ts in d.index]
    m = d.melt("zi", var_name="serie", value_name="kWh")
    m["serie"] = m["serie"].map(cols)
    colors = {"Producție": PV_COLOR, "Consum": LOAD_COLOR, "Export": "#7cb342", "Import": "#c0504d",
              "Autoconsum": "#8e7cc3"}
    labels = list(cols.values())
    return alt.Chart(m).mark_bar().encode(
        x=alt.X("zi:N", title=None, sort=list(d["zi"]), axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("serie:N", sort=labels),
        y=alt.Y("kWh:Q", title="kWh pe zi"),
        color=alt.Color("serie:N", sort=labels, title=None,
                        scale=alt.Scale(domain=labels, range=[colors.get(lab, "#888") for lab in labels]),
                        legend=alt.Legend(orient="top")),
        tooltip=["zi", "serie", alt.Tooltip("kWh:Q", format=".1f")],
    ).properties(height=260)


SEVERITY_ICON = {"worth_checking": ":material/warning:", "ok": ":material/check_circle:", "info": ":material/info:"}


def show_check(c: dict) -> None:
    sev = c.get("severity")
    if sev == "worth_checking":
        st.warning(c["message"], icon=":material/warning:")
    elif sev == "ok":
        st.success(c["message"], icon=":material/check_circle:")
    else:
        st.info(c["message"], icon=":material/info:")
