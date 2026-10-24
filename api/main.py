"""Mobile API. Wraps engine/, bills/, rules/ (no Streamlit) and the same database as the web app.

    uvicorn api.main:app --reload --port 8000        # docs at /docs
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from alerts import ntfy
from alerts.rules_publish import simulate_for_user
from api import auth, services
from api.auth import current_user, require_premium, require_site
from billing import stripe_checkout as sc
from bills.parse import parse_bill
from db import repo
from db.client import init_db
from db.seed import DEMO_EMAIL, DEMO_PASSWORD, ensure_admin, seed_demo
from engine import pvgis, weather
from engine import plan_service, planner as planner_mod
from engine.demand import SOURCE_LABELS
from engine.devices import CATALOG, KINDS
from engine.pipeline import train_models
from engine.profiles import AREAS, USAGE_TYPES
from engine.solar import Site
from ingest.detect import guess_mapping, read_table
from ingest.normalize import normalize
from rules.compensation import CUSTOMER_TYPES, STAGED_DIR, load_rule_file

MAX_UPLOAD = 15 * 1024 * 1024
RETURN_SCHEMES = ("prosumer://", "exp://", "exps://")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    ensure_admin()
    if os.environ.get("SEED_DEMO", "1") == "1":
        try:
            seed_demo()
        except Exception as exc:  # noqa: BLE001 - the API must start even without the demo
            print(f"demo seed failed: {exc}")
    yield


app = FastAPI(title="Asistent Prosumator API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- models
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class SiteIn(BaseModel):
    lat: float = Field(ge=43.0, le=49.0)      # Romania and a margin
    lon: float = Field(ge=19.0, le=31.0)
    elevation: float | None = None
    kwp: float = Field(ge=0, le=400)            # 0 = no panels yet (planning a system)
    tilt: float = Field(ge=0, le=90)
    azimuth: float = Field(ge=0, le=360)
    inverter_kw: float | None = Field(default=None, ge=0)
    battery_kwh: float = Field(default=0, ge=0)
    supplier: str | None = None
    customer_type: str = "individual"
    compensation_type: str = "quantity"
    price_lei_kwh: float | None = Field(default=None, ge=0, le=5)
    monthly_kwh: float | None = Field(default=None, ge=0)
    carryover_kwh: float = Field(default=0, ge=0)


class LineIn(BaseModel):
    line_type: str
    label_raw: str | None = None
    qty_kwh: float | None = None
    unit_price: float | None = None
    amount_lei: float | None = None
    confidence: float | None = 1.0


class ConfirmIn(BaseModel):
    supplier: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    pod: str | None = None
    total_lei: float | None = None
    vat_rate: float | None = None
    lines: list[LineIn] | None = None


class CheckIn(BaseModel):
    threshold_pct: float = Field(default=10, ge=1, le=50)
    carried_in_kwh: float | None = Field(default=None, ge=0)


class CheckoutIn(BaseModel):
    return_url: str


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str
    power_w: float | None = Field(default=None, ge=0, le=50000)
    hours_per_day: float | None = Field(default=None, ge=0, le=24)
    start_hour: int | None = Field(default=None, ge=0, le=23)
    days_per_week: int | None = Field(default=None, ge=0, le=7)
    months: list[int] | None = None
    flexible: bool = False
    is_new: bool = True
    annual_kwh: float | None = Field(default=None, ge=0, le=100000)
    ev_km_day: float | None = Field(default=None, ge=0, le=1000)
    ev_kwh_100km: float | None = Field(default=None, ge=0, le=100)
    quantity: int = Field(default=1, ge=1, le=50)


def _session(user: dict) -> dict:
    return {"token": auth.sign(user["id"]), **services.me(user)}


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Fișierul depășește 15 MB.")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fișier gol.")
    return data


# ---------------------------------------------------------------- health and auth
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/login")
def login(body: Credentials):
    user = repo.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "E-mail sau parolă greșită.")
    return _session(user)


@app.post("/auth/register")
def register(body: Credentials):
    if repo.get_user_by_email(body.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Există deja un cont cu acest e-mail.")
    return _session(repo.create_user(body.email, body.password))


@app.post("/auth/demo")
def demo_login():
    user = repo.authenticate(DEMO_EMAIL, DEMO_PASSWORD)
    if not user:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Contul demo nu este pregătit încă.")
    return _session(user)


@app.get("/me")
def get_me(user: dict = Depends(current_user)):
    return services.me(user)


# ---------------------------------------------------------------- profile
@app.put("/site")
def put_site(body: SiteIn, user: dict = Depends(current_user)):
    if body.customer_type not in CUSTOMER_TYPES:
        raise HTTPException(422, "Tip client necunoscut.")
    old = repo.get_site_for_user(user["id"]) or {}
    fields = body.model_dump()
    if fields.get("elevation") is None:
        fields["elevation"] = old.get("elevation") or weather.elevation(body.lat, body.lon) or 0.0
    if fields.get("inverter_kw") in (None, 0):
        fields["inverter_kw"] = body.kwp or None
    if old.get("label"):
        fields["label"] = old["label"]
    site = repo.upsert_site(user["id"], fields)
    if body.kwp > 0 and (any(old.get(k) != fields[k] for k in ("lat", "lon", "kwp", "tilt", "azimuth"))
                         or not site.get("pvgis_annual_kwh")):
        try:
            pv = pvgis.fetch(Site.from_row(site))
            repo.update_site(site["id"], pvgis_annual_kwh=pv["annual_kwh"], pvgis_monthly_json=pv["monthly_kwh"])
        except pvgis.PVGISUnavailable:
            pass
    services.clear_forecast_cache()
    return services.me(user)


@app.get("/geocode")
def geocode(q: str = Query(min_length=2), _: dict = Depends(current_user)):
    return weather.geocode(q)


# ---------------------------------------------------------------- bills
@app.post("/bills")
async def upload_bill(file: UploadFile = File(...), us: tuple = Depends(require_site)):
    user, site = us
    data = await _read_upload(file)
    try:
        parsed = parse_bill(data, file.filename or "")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    bill_id = services.save_draft(site, parsed)
    detail = services.bill_detail(bill_id, user, site)
    detail.update({"warnings": parsed["warnings"], "ocr_confidence": parsed["ocr_confidence"],
                   "validation": [{"ok": c["ok"], "message": c["message"]} for c in parsed["validation"]]})
    return detail


@app.get("/bills")
def list_bills(us: tuple = Depends(require_site)):
    return services.bill_list(us[1])


@app.get("/bills/{bill_id}")
def get_bill(bill_id: int, us: tuple = Depends(require_site)):
    detail = services.bill_detail(bill_id, *us)
    if not detail:
        raise HTTPException(404, "Factura nu există.")
    return detail


@app.post("/bills/{bill_id}/confirm")
def confirm_bill(bill_id: int, body: ConfirmIn, us: tuple = Depends(require_site)):
    user, site = us
    bill = repo.get_bill(bill_id)
    if not bill or bill["site_id"] != site["id"]:
        raise HTTPException(404, "Factura nu există.")
    changes = body.model_dump(exclude_none=True)
    if body.lines is not None:
        changes["lines"] = [ln.model_dump() for ln in body.lines]
    services.confirm(bill_id, changes)
    return services.bill_detail(bill_id, user, site)


@app.post("/bills/{bill_id}/check")
def recheck_bill(bill_id: int, body: CheckIn, us: tuple = Depends(require_site)):
    user, site = us
    require_premium(user)
    bill = repo.get_bill(bill_id)
    if not bill or bill["site_id"] != site["id"]:
        raise HTTPException(404, "Factura nu există.")
    services.run_bill_checks(bill, site, threshold=body.threshold_pct, carried_in=body.carried_in_kwh)
    return services.bill_detail(bill_id, user, site)


@app.delete("/bills/{bill_id}")
def delete_bill(bill_id: int, us: tuple = Depends(require_site)):
    bill = repo.get_bill(bill_id)
    if not bill or bill["site_id"] != us[1]["id"]:
        raise HTTPException(404, "Factura nu există.")
    repo.delete_bill(bill_id)
    return {"deleted": bill_id}


# ---------------------------------------------------------------- inverter data and models
@app.post("/readings")
async def upload_readings(file: UploadFile = File(...), us: tuple = Depends(require_site)):
    _, site = us
    data = await _read_upload(file)
    try:
        raw = read_table(data, file.filename or "export.csv")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(422, f"Nu am putut citi fișierul: {exc}") from exc
    g = guess_mapping(raw)
    if "timestamp" not in g["mapping"] or not ({"pv", "grid_export", "grid_import"} & set(g["mapping"])):
        raise HTTPException(422, {"message": "Nu am recunoscut coloanele. Folosiți aplicația web (Date invertor) "
                                             "pentru a le alege manual.", "columns": list(raw.columns)})
    try:
        hourly, rep = normalize(raw, g["mapping"], g["units"], g["kind"], g["label"], g["timezone"], g["dayfirst"],
                                kwp=float(site["kwp"]))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    n = repo.save_readings(site["id"], hourly)
    services.clear_forecast_cache()
    report = {k: rep[k] for k in ("interval_minutes", "gap_hours", "duplicates_removed", "warnings", "totals_kwh")}
    report.update({k: rep[k].tz_convert("Europe/Bucharest").isoformat() for k in ("start", "end")})
    return {"hours": n, "format": g["format"], "mapping": g["mapping"], "report": report}


@app.get("/readings/summary")
def readings_summary(us: tuple = Depends(require_site)):
    s = repo.readings_summary(us[1]["id"])
    loc = {k: s[k].tz_convert("Europe/Bucharest").isoformat() if s[k] is not None else None for k in ("start", "end")}
    return {**s, **loc}


@app.post("/models/train")
def train(us: tuple = Depends(require_site)):
    report = train_models(repo.get_site(us[1]["id"]))
    services.clear_forecast_cache()
    return report


# ---------------------------------------------------------------- forecast
@app.get("/forecast")
def get_forecast(force: bool = False, us: tuple = Depends(require_site)):
    user, site = us
    require_premium(user)
    return services.forecast(site, force=force)


@app.get("/forecast/summary")
def get_forecast_summary(us: tuple = Depends(require_site)):
    return services.forecast_summary(us[1])


# ---------------------------------------------------------------- alerts
@app.get("/alerts")
def get_alerts(user: dict = Depends(current_user)):
    return services.alerts(user, repo.get_site_for_user(user["id"]))


@app.post("/alerts/test")
def test_alert(user: dict = Depends(current_user)):
    ok = ntfy.send(user.get("ntfy_topic"), "Asistent Prosumator",
                   "Notificările funcționează. Vă anunțăm când se schimbă regulile.", tags=["white_check_mark"])
    return {"delivered": ok}


@app.post("/alerts/demo")
def demo_alert(us: tuple = Depends(require_site)):
    """Stage demo: personalised note for an invented rule, sent to this user only. Not published."""
    user, site = us
    path = STAGED_DIR / "demo_next_version.yaml"
    if not path.exists():
        raise HTTPException(404, "Regula demo lipsește.")
    res = simulate_for_user(load_rule_file(path), user, site)
    return {"delivered": res["delivered"], "title": res["title"], "message": res["message"]}


# ---------------------------------------------------------------- subscription (Stripe test mode)
def _api_base() -> str:
    return (os.environ.get("API_URL") or "http://localhost:8000").rstrip("/")


@app.get("/subscription")
def subscription(user: dict = Depends(current_user)):
    sub = repo.latest_subscription(user["id"])
    return {"plan": user["plan"], "premium": user["plan"] == "premium", "stripe_configured": sc.configured(),
            "demo_unlock": not sc.configured() and (user["email"] == DEMO_EMAIL or bool(user.get("is_admin"))),
            "current_period_end": sub["current_period_end"].isoformat() if sub and sub.get("current_period_end") else None,
            "test_card": "4242 4242 4242 4242"}


@app.post("/subscription/checkout")
def checkout(body: CheckoutIn, user: dict = Depends(current_user)):
    if not body.return_url.startswith(RETURN_SCHEMES):
        raise HTTPException(422, "Adresă de întoarcere nepermisă.")
    if not sc.configured():
        raise HTTPException(409, "Stripe nu este configurat pe server.")
    state = auth.sign(user["id"], ttl_s=3600, purpose="stripe")
    back = quote(body.return_url, safe="")
    success = f"{_api_base()}/stripe/return?session_id={{CHECKOUT_SESSION_ID}}&s={state}&r={back}"
    cancel = f"{_api_base()}/stripe/return?canceled=1&s={state}&r={back}"
    url = sc.create_checkout(user["email"], user["id"], _api_base(), "", success_url=success, cancel_url=cancel)
    return {"url": url}


@app.get("/stripe/return")
def stripe_return(s: str, r: str, session_id: str | None = None, canceled: int = 0):
    """Stripe redirects the in-app browser here; we confirm the session and bounce back into the app."""
    if not r.startswith(RETURN_SCHEMES):
        raise HTTPException(422, "Adresă de întoarcere nepermisă.")
    uid = auth.verify(s, purpose="stripe")
    result = "canceled" if canceled else "failed"
    if uid and session_id and not canceled:
        if repo.session_already_used(session_id):
            result = "ok"
        else:
            try:
                res = sc.verify_session(session_id, uid)
            except Exception:  # noqa: BLE001
                res = {"ok": False}
            if res["ok"]:
                repo.update_user(uid, plan="premium", stripe_customer_id=res.get("customer"))
                repo.add_subscription(uid, session_id, "active", res.get("period_end"))
                result = "ok"
    sep = "&" if "?" in r else "?"
    target = f"{r}{sep}{urlencode({'status': result})}"
    return RedirectResponse(target, status_code=302)


@app.post("/subscription/demo-unlock")
def demo_unlock(user: dict = Depends(current_user)):
    if sc.configured() or not (user["email"] == DEMO_EMAIL or user.get("is_admin")):
        raise HTTPException(403, "Disponibil doar pentru contul demo, când Stripe nu este configurat.")
    repo.update_user(user["id"], plan="premium")
    return services.me(repo.get_user(user["id"]))


@app.post("/subscription/cancel")
def cancel(user: dict = Depends(current_user)):
    repo.update_user(user["id"], plan="free")
    return services.me(repo.get_user(user["id"]))


# ---------------------------------------------------------------- planner
@app.get("/plan/catalog")
def plan_catalog(_: dict = Depends(current_user)):
    return {"catalog": CATALOG, "kinds": KINDS, "usage_types": USAGE_TYPES, "areas": AREAS,
            "defaults": planner_mod.DEFAULT_SETTINGS, "scenarios": planner_mod.SCENARIOS,
            "baseline_sources": SOURCE_LABELS}


@app.get("/plan/settings")
def get_plan_settings(us: tuple = Depends(require_site)):
    return planner_mod.settings_with_defaults(repo.get_plan_settings(us[1]["id"]))


@app.put("/plan/settings")
def put_plan_settings(body: dict, us: tuple = Depends(require_site)):
    clean_settings = {k: v for k, v in body.items() if k in planner_mod.DEFAULT_SETTINGS}
    merged = {**repo.get_plan_settings(us[1]["id"]), **clean_settings}
    return planner_mod.settings_with_defaults(repo.save_plan_settings(us[1]["id"], merged))


@app.get("/devices")
def list_devices(us: tuple = Depends(require_site)):
    return repo.list_devices(us[1]["id"])


@app.post("/devices")
def add_device(body: DeviceIn, us: tuple = Depends(require_site)):
    if body.kind not in KINDS:
        raise HTTPException(422, "Tip de aparat necunoscut.")
    return repo.save_device(us[1]["id"], body.model_dump())


@app.put("/devices/{device_id}")
def edit_device(device_id: int, body: DeviceIn, us: tuple = Depends(require_site)):
    dev = repo.get_device(device_id)
    if not dev or dev["site_id"] != us[1]["id"]:
        raise HTTPException(404, "Aparatul nu există.")
    if body.kind not in KINDS:
        raise HTTPException(422, "Tip de aparat necunoscut.")
    return repo.save_device(us[1]["id"], body.model_dump(), device_id)


@app.delete("/devices/{device_id}")
def remove_device(device_id: int, us: tuple = Depends(require_site)):
    dev = repo.get_device(device_id)
    if not dev or dev["site_id"] != us[1]["id"]:
        raise HTTPException(404, "Aparatul nu există.")
    repo.delete_device(us[1]["id"], device_id)
    return {"deleted": device_id}


@app.post("/plan")
def compute_plan(force: bool = False, us: tuple = Depends(require_site)):
    from api.serialize import clean
    return clean(plan_service.plan_for_site(repo.get_site(us[1]["id"]), force=force))


@app.get("/", response_class=HTMLResponse)
def root():
    return "<h1>Asistent Prosumator API</h1><p>Documentație: <a href='/docs'>/docs</a></p>"
