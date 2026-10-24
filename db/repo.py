"""Data access. Plain functions over SQLAlchemy Core; no Streamlit imports.

All timestamps go in and come out as UTC. SQLite has no time zones, so values are
stored there as naive UTC and re-labelled UTC on the way out.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets
from datetime import date, datetime, timezone
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import and_, delete, func, insert, select, update

from db import models as m
from db.client import get_engine

READING_COLS = ["pv_kwh", "load_kwh", "grid_import_kwh", "grid_export_kwh",
                "batt_charge_kwh", "batt_discharge_kwh", "soc_pct"]
WEATHER_COLS = ["ghi", "dni", "dhi", "temp_c", "wind_ms", "cloud_pct"]
FORECAST_COLS = ["pv_p10", "pv_p50", "pv_p90", "pv_physics", "load_p50"]


# ---------------------------------------------------------------- helpers
def _is_sqlite() -> bool:
    return get_engine().dialect.name == "sqlite"


def _dt(value) -> datetime | None:
    """Python datetime in UTC, naive for SQLite."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    py = ts.to_pydatetime()
    return py.replace(tzinfo=None) if _is_sqlite() else py


def _utc_index(values: Iterable) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.to_datetime(list(values), utc=True))


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if hasattr(v, "item"):  # numpy scalar
        v = v.item()
        if isinstance(v, float) and math.isnan(v):
            return None
    return v


def _row(r) -> dict:
    return dict(r._mapping) if r is not None else None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- users
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"pbkdf2_sha256$200000${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters)).hex()
    return hmac.compare_digest(check, digest)


def new_ntfy_topic() -> str:
    return "prosumer-" + secrets.token_urlsafe(12).replace("_", "").replace("-", "").lower()[:14]


def create_user(email: str, password: str, is_admin: bool = False) -> dict:
    email = email.strip().lower()
    with get_engine().begin() as c:
        c.execute(insert(m.users).values(
            email=email, password_hash=hash_password(password), plan="free",
            ntfy_topic=new_ntfy_topic(), is_admin=is_admin))
    return get_user_by_email(email)


def get_user_by_email(email: str) -> dict | None:
    with get_engine().connect() as c:
        return _row(c.execute(select(m.users).where(m.users.c.email == email.strip().lower())).first())


def get_user(user_id: int) -> dict | None:
    with get_engine().connect() as c:
        return _row(c.execute(select(m.users).where(m.users.c.id == user_id)).first())


def authenticate(email: str, password: str) -> dict | None:
    user = get_user_by_email(email)
    if user and verify_password(password, user["password_hash"]):
        return user
    return None


def update_user(user_id: int, **fields) -> None:
    with get_engine().begin() as c:
        c.execute(update(m.users).where(m.users.c.id == user_id).values(**fields))


def list_users_with_sites() -> list[dict]:
    j = m.users.join(m.sites, m.sites.c.user_id == m.users.c.id)
    q = select(m.users.c.id.label("user_id"), m.users.c.email, m.users.c.ntfy_topic,
               m.users.c.plan, m.sites).select_from(j)
    with get_engine().connect() as c:
        return [_row(r) for r in c.execute(q)]


# ---------------------------------------------------------------- sites
SITE_FIELDS = {c.name for c in m.sites.columns} - {"id", "user_id"}


def get_site_for_user(user_id: int) -> dict | None:
    with get_engine().connect() as c:
        return _row(c.execute(select(m.sites).where(m.sites.c.user_id == user_id)).first())


def get_site(site_id: int) -> dict | None:
    with get_engine().connect() as c:
        return _row(c.execute(select(m.sites).where(m.sites.c.id == site_id)).first())


def upsert_site(user_id: int, fields: dict) -> dict:
    data = {k: _clean(v) for k, v in fields.items() if k in SITE_FIELDS}
    existing = get_site_for_user(user_id)
    with get_engine().begin() as c:
        if existing:
            c.execute(update(m.sites).where(m.sites.c.id == existing["id"]).values(**data))
        else:
            c.execute(insert(m.sites).values(user_id=user_id, **data))
    return get_site_for_user(user_id)


def update_site(site_id: int, **fields) -> None:
    data = {k: _clean(v) for k, v in fields.items() if k in SITE_FIELDS}
    with get_engine().begin() as c:
        c.execute(update(m.sites).where(m.sites.c.id == site_id).values(**data))


def list_sites() -> list[dict]:
    with get_engine().connect() as c:
        return [_row(r) for r in c.execute(select(m.sites))]


# ---------------------------------------------------------------- readings
def save_readings(site_id: int, df: pd.DataFrame) -> int:
    """Replace readings for the time range covered by df (index = UTC hour start)."""
    if df.empty:
        return 0
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC") if df.index.tz else pd.DatetimeIndex(df.index).tz_localize("UTC")
    cols = [c for c in READING_COLS if c in df.columns]
    rows = [
        {"site_id": site_id, "ts": _dt(ts), **{c: _clean(row[c]) for c in cols}}
        for ts, row in df[cols].iterrows()
    ]
    with get_engine().begin() as c:
        c.execute(delete(m.readings).where(and_(
            m.readings.c.site_id == site_id,
            m.readings.c.ts >= _dt(df.index.min()),
            m.readings.c.ts <= _dt(df.index.max()))))
        for i in range(0, len(rows), 2000):
            c.execute(insert(m.readings), rows[i:i + 2000])
    return len(rows)


def load_readings(site_id: int, start=None, end=None) -> pd.DataFrame:
    q = select(m.readings).where(m.readings.c.site_id == site_id)
    if start is not None:
        q = q.where(m.readings.c.ts >= _dt(start))
    if end is not None:
        q = q.where(m.readings.c.ts < _dt(end))
    q = q.order_by(m.readings.c.ts)
    with get_engine().connect() as c:
        rows = c.execute(q).fetchall()
    if not rows:
        return pd.DataFrame(columns=READING_COLS, index=pd.DatetimeIndex([], tz="UTC", name="ts"))
    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df.index = _utc_index(df.pop("ts"))
    df.index.name = "ts"
    return df[READING_COLS].astype(float)


def readings_summary(site_id: int) -> dict:
    q = select(func.count(), func.min(m.readings.c.ts), func.max(m.readings.c.ts),
               func.count(m.readings.c.load_kwh), func.count(m.readings.c.grid_export_kwh)
               ).where(m.readings.c.site_id == site_id)
    with get_engine().connect() as c:
        n, lo, hi, n_load, n_export = c.execute(q).first()
    return {
        "rows": n or 0,
        "start": _ts(lo),
        "end": _ts(hi),
        "has_load": (n_load or 0) > 0,
        "has_export": (n_export or 0) > 0,
    }


def _ts(value) -> pd.Timestamp | None:
    if value is None:
        return None
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def delete_readings(site_id: int) -> None:
    with get_engine().begin() as c:
        c.execute(delete(m.readings).where(m.readings.c.site_id == site_id))


# ---------------------------------------------------------------- weather cache (historical)
def _r(x: float) -> float:
    return round(float(x), 2)


def save_weather(lat: float, lon: float, df: pd.DataFrame, kind: str) -> None:
    if df.empty:
        return
    rows = [{"lat_r": _r(lat), "lon_r": _r(lon), "ts": _dt(ts), "kind": kind, "fetched_at": _dt(now_utc()),
             **{c: _clean(row.get(c)) for c in WEATHER_COLS}} for ts, row in df.iterrows()]
    with get_engine().begin() as c:
        c.execute(delete(m.weather).where(and_(
            m.weather.c.lat_r == _r(lat), m.weather.c.lon_r == _r(lon), m.weather.c.kind == kind,
            m.weather.c.ts >= _dt(df.index.min()), m.weather.c.ts <= _dt(df.index.max()))))
        for i in range(0, len(rows), 2000):
            c.execute(insert(m.weather), rows[i:i + 2000])


def load_weather(lat: float, lon: float, start, end, kind: str) -> pd.DataFrame:
    q = select(m.weather).where(and_(
        m.weather.c.lat_r == _r(lat), m.weather.c.lon_r == _r(lon), m.weather.c.kind == kind,
        m.weather.c.ts >= _dt(start), m.weather.c.ts < _dt(end))).order_by(m.weather.c.ts)
    with get_engine().connect() as c:
        rows = c.execute(q).fetchall()
    if not rows:
        return pd.DataFrame(columns=WEATHER_COLS)
    df = pd.DataFrame([dict(r._mapping) for r in rows])
    df.index = _utc_index(df.pop("ts"))
    return df[WEATHER_COLS].astype(float)


# ---------------------------------------------------------------- forecasts
def save_forecast(site_id: int, df: pd.DataFrame, model_version: str) -> datetime:
    run_at = now_utc().replace(microsecond=0)
    cols = [c for c in FORECAST_COLS if c in df.columns]
    rows = [{"site_id": site_id, "run_at": _dt(run_at), "ts": _dt(ts), "model_version": model_version,
             **{c: _clean(row[c]) for c in cols}} for ts, row in df[cols].iterrows()]
    with get_engine().begin() as c:
        c.execute(delete(m.forecasts).where(m.forecasts.c.site_id == site_id))  # keep the latest run only
        c.execute(insert(m.forecasts), rows)
    return run_at


def load_latest_forecast(site_id: int) -> tuple[datetime | None, pd.DataFrame, str | None]:
    with get_engine().connect() as c:
        run_at = c.execute(select(func.max(m.forecasts.c.run_at)).where(m.forecasts.c.site_id == site_id)).scalar()
        if run_at is None:
            return None, pd.DataFrame(columns=FORECAST_COLS), None
        rows = c.execute(select(m.forecasts).where(and_(
            m.forecasts.c.site_id == site_id, m.forecasts.c.run_at == run_at)).order_by(m.forecasts.c.ts)).fetchall()
    df = pd.DataFrame([dict(r._mapping) for r in rows])
    version = df["model_version"].iloc[0]
    df.index = _utc_index(df.pop("ts"))
    run_ts = pd.Timestamp(run_at)
    run_ts = run_ts.tz_localize("UTC") if run_ts.tzinfo is None else run_ts
    return run_ts.to_pydatetime(), df[FORECAST_COLS].astype(float), version


# ---------------------------------------------------------------- models
def save_model(site_id: int, kind: str, artifact: bytes, metrics: dict) -> None:
    with get_engine().begin() as c:
        c.execute(delete(m.models).where(and_(m.models.c.site_id == site_id, m.models.c.kind == kind)))
        c.execute(insert(m.models).values(site_id=site_id, kind=kind, artifact=artifact,
                                          metrics_json=metrics, trained_at=_dt(now_utc())))


def load_model(site_id: int, kind: str) -> dict | None:
    q = select(m.models).where(and_(m.models.c.site_id == site_id, m.models.c.kind == kind)) \
        .order_by(m.models.c.trained_at.desc())
    with get_engine().connect() as c:
        return _row(c.execute(q).first())


def delete_models(site_id: int) -> None:
    with get_engine().begin() as c:
        c.execute(delete(m.models).where(m.models.c.site_id == site_id))


# ---------------------------------------------------------------- bills
BILL_FIELDS = {c.name for c in m.bills.columns} - {"id", "created_at"}
LINE_FIELDS = {"line_type", "label_raw", "qty_kwh", "unit_price", "amount_lei", "confidence", "user_confirmed"}


def save_bill(site_id: int, bill: dict, lines: list[dict]) -> int:
    data = {k: _clean(v) for k, v in bill.items() if k in BILL_FIELDS}
    data["site_id"] = site_id
    with get_engine().begin() as c:
        bill_id = c.execute(insert(m.bills).values(**data)).inserted_primary_key[0]
        if lines:
            c.execute(insert(m.bill_lines), [
                {"bill_id": bill_id, **{k: _clean(v) for k, v in ln.items() if k in LINE_FIELDS}} for ln in lines])
    return int(bill_id)


def update_bill(bill_id: int, bill: dict, lines: list[dict] | None = None) -> None:
    data = {k: _clean(v) for k, v in bill.items() if k in BILL_FIELDS and k != "site_id"}
    with get_engine().begin() as c:
        if data:
            c.execute(update(m.bills).where(m.bills.c.id == bill_id).values(**data))
        if lines is not None:
            c.execute(delete(m.bill_lines).where(m.bill_lines.c.bill_id == bill_id))
            if lines:
                c.execute(insert(m.bill_lines), [
                    {"bill_id": bill_id, **{k: _clean(v) for k, v in ln.items() if k in LINE_FIELDS}} for ln in lines])


def list_bills(site_id: int) -> list[dict]:
    q = select(m.bills).where(m.bills.c.site_id == site_id).order_by(m.bills.c.period_end.desc(), m.bills.c.id.desc())
    with get_engine().connect() as c:
        return [_row(r) for r in c.execute(q)]


def get_bill(bill_id: int) -> dict | None:
    with get_engine().connect() as c:
        bill = _row(c.execute(select(m.bills).where(m.bills.c.id == bill_id)).first())
        if not bill:
            return None
        bill["lines"] = [_row(r) for r in c.execute(
            select(m.bill_lines).where(m.bill_lines.c.bill_id == bill_id).order_by(m.bill_lines.c.id))]
    return bill


def delete_bill(bill_id: int) -> None:
    with get_engine().begin() as c:
        c.execute(delete(m.bill_checks).where(m.bill_checks.c.bill_id == bill_id))
        c.execute(delete(m.bill_lines).where(m.bill_lines.c.bill_id == bill_id))
        c.execute(delete(m.bills).where(m.bills.c.id == bill_id))


def save_checks(bill_id: int, checks: list[dict]) -> None:
    keys = {"check_type", "expected", "actual", "diff_pct", "severity", "message"}
    with get_engine().begin() as c:
        c.execute(delete(m.bill_checks).where(m.bill_checks.c.bill_id == bill_id))
        if checks:
            c.execute(insert(m.bill_checks), [
                {"bill_id": bill_id, **{k: _clean(v) for k, v in ch.items() if k in keys}} for ch in checks])


def get_checks(bill_id: int) -> list[dict]:
    with get_engine().connect() as c:
        return [_row(r) for r in c.execute(
            select(m.bill_checks).where(m.bill_checks.c.bill_id == bill_id).order_by(m.bill_checks.c.id))]


# ---------------------------------------------------------------- rules
def upsert_rule(rule: dict) -> bool:
    """Insert or update a rule version. Returns True when it is new."""
    data = {
        "id": rule["id"], "version": int(rule["version"]),
        "effective_from": rule["effective_from"] if isinstance(rule["effective_from"], date)
        else date.fromisoformat(str(rule["effective_from"])),
        "title": rule.get("title"), "applies_to_json": rule.get("applies_to", {}),
        "params_json": _jsonable(rule.get("params", {})), "source": rule.get("source"),
        "source_url": rule.get("source_url"), "summary": rule.get("summary_ro"),
    }
    with get_engine().begin() as c:
        exists = c.execute(select(m.rules.c.id).where(m.rules.c.id == data["id"])).first()
        if exists:
            c.execute(update(m.rules).where(m.rules.c.id == data["id"]).values(**data))
            return False
        c.execute(insert(m.rules).values(published_at=_dt(now_utc()), **data))
        return True


def list_rules() -> list[dict]:
    with get_engine().connect() as c:
        return [_row(r) for r in c.execute(select(m.rules).order_by(m.rules.c.effective_from))]


def _jsonable(obj: Any):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj


# ---------------------------------------------------------------- subscriptions
def add_subscription(user_id: int, session_id: str, status: str, period_end=None) -> None:
    with get_engine().begin() as c:
        c.execute(insert(m.subscriptions).values(user_id=user_id, stripe_session_id=session_id,
                                                 status=status, current_period_end=_dt(period_end)))


def session_already_used(session_id: str) -> bool:
    with get_engine().connect() as c:
        return c.execute(select(m.subscriptions.c.id).where(
            m.subscriptions.c.stripe_session_id == session_id)).first() is not None


def latest_subscription(user_id: int) -> dict | None:
    q = select(m.subscriptions).where(m.subscriptions.c.user_id == user_id).order_by(m.subscriptions.c.id.desc())
    with get_engine().connect() as c:
        return _row(c.execute(q).first())


# ---------------------------------------------------------------- notifications
def add_notification(user_id: int, ntype: str, payload: dict, delivered: bool) -> None:
    with get_engine().begin() as c:
        c.execute(insert(m.notifications).values(user_id=user_id, type=ntype, payload_json=_jsonable(payload),
                                                 delivered=delivered, sent_at=_dt(now_utc())))


def list_notifications(user_id: int, limit: int = 20) -> list[dict]:
    q = select(m.notifications).where(m.notifications.c.user_id == user_id) \
        .order_by(m.notifications.c.id.desc()).limit(limit)
    with get_engine().connect() as c:
        return [_row(r) for r in c.execute(q)]


# ---------------------------------------------------------------- key-value
def kv_get(key: str) -> str | None:
    with get_engine().connect() as c:
        return c.execute(select(m.kv.c.value).where(m.kv.c.key == key)).scalar()


def kv_set(key: str, value: str) -> None:
    with get_engine().begin() as c:
        if c.execute(select(m.kv.c.key).where(m.kv.c.key == key)).first():
            c.execute(update(m.kv).where(m.kv.c.key == key).values(value=value, updated_at=_dt(now_utc())))
        else:
            c.execute(insert(m.kv).values(key=key, value=value, updated_at=_dt(now_utc())))


# ---------------------------------------------------------------- planner: devices and settings
DEVICE_FIELDS = {"name", "kind", "power_w", "hours_per_day", "start_hour", "days_per_week", "flexible", "is_new",
                 "annual_kwh", "ev_km_day", "ev_kwh_100km", "quantity"}


def _device_out(row) -> dict:
    d = _row(row)
    d["months"] = d.pop("months_json") or list(range(1, 13))
    return d


def list_devices(site_id: int) -> list[dict]:
    with get_engine().connect() as c:
        return [_device_out(r) for r in c.execute(
            select(m.devices).where(m.devices.c.site_id == site_id).order_by(m.devices.c.id))]


def get_device(device_id: int) -> dict | None:
    with get_engine().connect() as c:
        r = c.execute(select(m.devices).where(m.devices.c.id == device_id)).first()
    return _device_out(r) if r else None


def save_device(site_id: int, dev: dict, device_id: int | None = None) -> dict:
    data = {k: _clean(v) for k, v in dev.items() if k in DEVICE_FIELDS}
    if "months" in dev:
        data["months_json"] = [int(x) for x in (dev["months"] or range(1, 13))]
    with get_engine().begin() as c:
        if device_id:
            c.execute(update(m.devices).where(and_(m.devices.c.id == device_id, m.devices.c.site_id == site_id))
                      .values(**data))
        else:
            device_id = c.execute(insert(m.devices).values(site_id=site_id, **data)).inserted_primary_key[0]
    return get_device(int(device_id))


def delete_device(site_id: int, device_id: int) -> None:
    with get_engine().begin() as c:
        c.execute(delete(m.devices).where(and_(m.devices.c.id == device_id, m.devices.c.site_id == site_id)))


def get_plan_settings(site_id: int) -> dict:
    with get_engine().connect() as c:
        v = c.execute(select(m.plan_settings.c.settings_json).where(m.plan_settings.c.site_id == site_id)).scalar()
    return dict(v or {})


def save_plan_settings(site_id: int, settings: dict) -> dict:
    data = _jsonable(settings)
    with get_engine().begin() as c:
        if c.execute(select(m.plan_settings.c.site_id).where(m.plan_settings.c.site_id == site_id)).first():
            c.execute(update(m.plan_settings).where(m.plan_settings.c.site_id == site_id)
                      .values(settings_json=data, updated_at=_dt(now_utc())))
        else:
            c.execute(insert(m.plan_settings).values(site_id=site_id, settings_json=data, updated_at=_dt(now_utc())))
    return get_plan_settings(site_id)
