"""Demo account: a Bucharest household with a year of synthetic inverter data and trained models.

Created on first app start (and by scripts/seed_demo.py). Login: demo@prosumer.demo / demo1234
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from db import repo
from db.client import init_db

DEMO_EMAIL = "demo@prosumer.demo"
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo1234")


def ensure_rules() -> None:
    from alerts.rules_publish import sync_from_files
    sync_from_files(notify=False)


def seed_demo(force: bool = False, train: bool = True) -> dict:
    from engine.pipeline import train_models
    from ingest.demo import DEMO_SITE, generate

    init_db()
    ensure_rules()
    user = repo.get_user_by_email(DEMO_EMAIL)
    if user and not force:
        site = repo.get_site_for_user(user["id"])
        summary = repo.readings_summary(site["id"]) if site else {"rows": 0}
        stale = summary.get("end") is None or summary["end"].date() < date.today() - timedelta(days=2)
        if not stale:
            return {"status": "exists", "user_id": user["id"]}
    if not user:
        user = repo.create_user(DEMO_EMAIL, DEMO_PASSWORD)
    site = repo.upsert_site(user["id"], DEMO_SITE)

    readings, weather = generate(date.today() - timedelta(days=1))
    repo.save_readings(site["id"], readings)
    repo.save_weather(site["lat"], site["lon"], weather, "demo")
    report = train_models(site) if train else {}
    return {"status": "seeded", "user_id": user["id"], "rows": len(readings), "training": report}


def ensure_admin() -> None:
    """ADMIN_EMAIL / ADMIN_PASSWORD from secrets: the team account that can publish rule versions."""
    email, password = os.environ.get("ADMIN_EMAIL"), os.environ.get("ADMIN_PASSWORD")
    if not email or not password:
        return
    user = repo.get_user_by_email(email)
    if not user:
        repo.create_user(email, password, is_admin=True)
    elif not user["is_admin"]:
        repo.update_user(user["id"], is_admin=True)
