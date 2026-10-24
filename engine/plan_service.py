"""Loads what the planner needs for one site from the database and runs it. Used by the web app and the API."""
from __future__ import annotations

import hashlib
import json
import time

from db import repo
from engine import calibrate, planner
from engine.demand import year_index

_CACHE: dict[str, tuple[float, dict]] = {}
TTL_S = 900


def _confirmed_bills(site_id: int) -> list[dict]:
    return [repo.get_bill(b["id"]) for b in repo.list_bills(site_id) if b["status"] == "confirmed"]


def _key(site: dict, settings: dict, devices: list[dict], extra: dict) -> str:
    blob = json.dumps({"site": {k: site.get(k) for k in sorted(site) if k != "pvgis_monthly_json"},
                       "settings": settings, "devices": devices, "extra": extra}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def plan_for_site(site: dict, force: bool = False) -> dict:
    settings = repo.get_plan_settings(site["id"])
    devices = repo.list_devices(site["id"])
    summary = repo.readings_summary(site["id"])
    model_row = repo.load_model(site["id"], "solar")
    bills = _confirmed_bills(site["id"])
    key = _key(site, settings, devices, {"rows": summary["rows"], "end": summary["end"],
                                          "model": model_row and model_row.get("trained_at"), "bills": len(bills),
                                          "day": time.strftime("%Y-%m-%d")})
    hit = _CACHE.get(key)
    if hit and not force and time.time() - hit[0] < TTL_S:
        return hit[1]
    index = year_index()
    readings = repo.load_readings(site["id"], start=index[0]) if summary["rows"] else None
    model = calibrate.SolarCorrection.from_bytes(model_row["artifact"]) if model_row else None
    result = planner.plan(site, settings, devices, readings, bills, model, index)
    if len(_CACHE) > 100:
        _CACHE.clear()
    _CACHE[key] = (time.time(), result)
    return result


def clear_cache() -> None:
    _CACHE.clear()
