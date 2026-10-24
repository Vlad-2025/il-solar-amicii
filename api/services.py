"""Shapes the domain objects (bills, forecasts, rules) into what the mobile app shows."""
from __future__ import annotations

import time
from datetime import date

import pandas as pd

from alerts import ntfy
from bills.check import check_bill
from bills.complaint import draft
from bills.validate import apply_confidence, validate
from db import repo
from engine.pipeline import all_rules, run_forecast
from rules.compensation import CUSTOMER_TYPES, previous_rule, rule_for
from rules.explain import LINE_LABELS, change_note, energy_balance, explain_line, why_pay_note

from api.serialize import clean, frame_records


# ---------------------------------------------------------------- users
def me(user: dict) -> dict:
    site = repo.get_site_for_user(user["id"])
    topic = user.get("ntfy_topic")
    return clean({
        "user": {"id": user["id"], "email": user["email"], "plan": user["plan"],
                 "premium": user["plan"] == "premium", "is_admin": bool(user.get("is_admin"))},
        "site": _site_public(site) if site else None,
        "needs_onboarding": site is None,
        "ntfy": {"topic": topic, "web_url": ntfy.subscribe_url(topic) if topic else None,
                 "app_url": ntfy.subscribe_url(topic).replace("https://", "ntfy://").replace("http://", "ntfy://") if topic else None},
    })


def _site_public(site: dict) -> dict:
    hidden = {"pvgis_monthly_json"}
    return {k: v for k, v in site.items() if k not in hidden}


# ---------------------------------------------------------------- bills
def _rule_for_bill(bill: dict, site: dict):
    return rule_for(bill.get("period_end") or date.today(), site.get("customer_type") or "individual",
                    float(site["kwp"]), all_rules())


def bill_detail(bill_id: int, user: dict, site: dict, run_checks: bool = True) -> dict:
    bill = repo.get_bill(bill_id)
    if not bill or bill["site_id"] != site["id"]:
        return {}
    rule = _rule_for_bill(bill, site)
    lines = [{
        "id": ln["id"], "line_type": ln["line_type"], "label": LINE_LABELS.get(ln["line_type"], ln["line_type"]),
        "label_raw": ln.get("label_raw"), "qty_kwh": ln.get("qty_kwh"), "unit_price": ln.get("unit_price"),
        "amount_lei": ln.get("amount_lei"), "confidence": ln.get("confidence"),
        "needs_review": (ln.get("confidence") or 0) < 0.8 and not ln.get("user_confirmed"),
        "explanation": explain_line(ln, rule, bill.get("vat_rate")),
    } for ln in bill["lines"]]
    premium = user.get("plan") == "premium"
    out = {
        **{k: bill.get(k) for k in ("id", "status", "supplier", "period_start", "period_end", "pod", "total_lei",
                                    "vat_rate", "confidence", "parse_method")},
        "lines": lines,
        "balance": energy_balance(bill["lines"]),
        "why_pay": why_pay_note(bill["lines"]),
        "rule": {"label": rule.label, "verified": rule.verified} if rule else None,
        "premium": premium, "checks": None, "complaint": None,
    }
    if premium and bill["status"] == "confirmed":
        checks = repo.get_checks(bill_id)
        if not checks and run_checks:
            checks = run_bill_checks(bill, site, rule)
        out["checks"] = [{k: c.get(k) for k in ("check_type", "expected", "actual", "diff_pct", "severity", "message")}
                         for c in checks]
        if any(c.get("severity") == "worth_checking" for c in checks):
            out["complaint"] = draft(bill, checks, site, user["email"])
    return clean(out)


def run_bill_checks(bill: dict, site: dict, rule=None, threshold: float = 10.0,
                    carried_in: float | None = None) -> list[dict]:
    rule = rule or _rule_for_bill(bill, site)
    checks = check_bill(bill, repo.load_readings(site["id"]), rule, carried_in, float(site["kwp"]), threshold)
    repo.save_checks(bill["id"], checks)
    return checks


def save_draft(site: dict, parsed: dict) -> int:
    return repo.save_bill(site["id"], {
        "supplier": parsed.get("supplier"), "period_start": parsed.get("period_start"),
        "period_end": parsed.get("period_end"), "pod": parsed.get("pod"), "total_lei": parsed.get("total_lei"),
        "vat_rate": parsed.get("vat_rate"), "parse_method": parsed.get("parse_method"),
        "confidence": parsed.get("confidence"), "status": "draft", "file_path": None,
    }, parsed["lines"])


def confirm(bill_id: int, changes: dict) -> None:
    bill = repo.get_bill(bill_id)
    lines = changes.get("lines")
    if lines is not None:
        lines = [{**ln, "user_confirmed": True, "confidence": ln.get("confidence", 1.0)} for ln in lines]
    else:
        lines = [{**ln, "user_confirmed": True} for ln in bill["lines"]]
    fields = {"lines": lines, "vat_rate": changes.get("vat_rate", bill.get("vat_rate"))}
    conf = apply_confidence(fields, validate(fields))
    update = {k: changes[k] for k in ("supplier", "period_start", "period_end", "pod", "total_lei", "vat_rate")
              if changes.get(k) is not None}
    repo.update_bill(bill_id, {**update, "status": "confirmed", "confidence": conf}, lines)
    repo.save_checks(bill_id, [])      # recomputed on next read


def bill_list(site: dict) -> list[dict]:
    out = []
    for b in repo.list_bills(site["id"]):
        if b["status"] != "confirmed":
            continue
        full = repo.get_bill(b["id"])
        bal = energy_balance(full["lines"])
        flagged = sum(1 for c in repo.get_checks(b["id"]) if c["severity"] == "worth_checking")
        out.append({"id": b["id"], "supplier": b.get("supplier"), "period_start": b.get("period_start"),
                    "period_end": b.get("period_end"), "total_lei": b.get("total_lei"),
                    "consumed_kwh": bal["consumed"], "delivered_kwh": bal["delivered"],
                    "compensated_kwh": bal["compensated"], "flagged": flagged})
    return clean(out)


# ---------------------------------------------------------------- forecast (cached 1 h per site/models/profile)
_CACHE: dict[tuple, tuple[float, dict]] = {}
SITE_KEY_FIELDS = ("lat", "lon", "kwp", "tilt", "azimuth", "inverter_kw", "battery_kwh", "customer_type",
                   "price_lei_kwh", "monthly_kwh", "carryover_kwh")


def forecast(site: dict, force: bool = False) -> dict:
    models_key = tuple(str((repo.load_model(site["id"], k) or {}).get("trained_at")) for k in ("solar", "load"))
    key = (site["id"], pd.Timestamp.now(tz="UTC").floor("h"), models_key, tuple(site.get(k) for k in SITE_KEY_FIELDS))
    hit = _CACHE.get(key)
    if hit and not force:
        return hit[1]
    fc = run_forecast(site, save=True)
    daily = fc["daily"]
    payload = clean({
        "weather_source": fc["weather_source"], "model_version": fc["model_version"],
        "load_method": fc["load_method"], "lead_note": fc["lead_note"],
        "hourly": frame_records(fc["hourly"], ["pv_p10", "pv_p50", "pv_p90", "load_p50", "exported", "imported"]),
        "daily": [{"date": ts.date().isoformat(), "pv": r["pv"], "load": r["load"], "self_consumed": r["self_consumed"],
                   "exported": r["exported"], "imported": r["imported"]} for ts, r in daily.iterrows()],
        "month": fc["month"],
        "rule": {"label": fc["rule"].label} if fc["rule"] else None,
        "solar_metrics": fc["solar_metrics"], "load_metrics": fc["load_metrics"],
    })
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[key] = (time.time(), payload)
    return payload


def forecast_summary(site: dict) -> dict:
    fc = forecast(site)
    return {"weather_source": fc["weather_source"], "lead_note": fc["lead_note"],
            "daily": [{"date": d["date"], "pv": d["pv"]} for d in fc["daily"]]}


def clear_forecast_cache() -> None:
    _CACHE.clear()


# ---------------------------------------------------------------- rules and alerts
def alerts(user: dict, site: dict | None) -> dict:
    out: dict = {"current_rule": None, "change": None}
    if site:
        ctype, kw = site.get("customer_type") or "individual", float(site["kwp"])
        rules = all_rules()
        cur = rule_for(date.today(), ctype, kw, rules)
        if cur:
            p = cur.params
            out["current_rule"] = {
                "title": cur.title, "version": cur.version, "effective_from": cur.effective_from,
                "summary": cur.summary_ro, "verified": cur.verified, "source": cur.source, "source_url": cur.source_url,
                "facts": [
                    ["Tip compensare", "cantitativă (kWh pentru kWh)" if p.get("compensation_type") == "quantity" else str(p.get("compensation_type"))],
                    ["Calcul", "lunar" if p.get("netting_period") == "month" else str(p.get("netting_period"))],
                    ["Limită putere", f"{p.get('quantity_compensation_max_kw')} kW"],
                    ["Disponibilă până la", str(p.get("quantity_compensation_until"))],
                    ["Valabilitate surplus", f"{p['carryover_months']} luni" if p.get("carryover_months") else "neverificată"],
                ],
            }
            note = change_note(previous_rule(cur, ctype, kw, rules), cur, ctype, kw)
            out["change"] = {"changes": note["changes"], "impact": note["impact"]}
        out["customer_type_label"] = CUSTOMER_TYPES.get(ctype, ctype)
    out["notifications"] = [{
        "id": n["id"], "type": n["type"], "sent_at": n.get("sent_at"), "delivered": n["delivered"],
        "title": (n["payload_json"] or {}).get("title"), "message": (n["payload_json"] or {}).get("message"),
        "simulated": bool((n["payload_json"] or {}).get("simulated")),
    } for n in repo.list_notifications(user["id"], limit=30)]
    return clean(out)
