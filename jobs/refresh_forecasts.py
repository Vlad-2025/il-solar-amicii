"""Daily job: recompute and store the 7-day forecast for every site; optionally retrain stale models.

    python -m jobs.refresh_forecasts
    python -m jobs.refresh_forecasts --retrain-older-than 7
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from db import repo
from db.client import init_db
from engine.pipeline import run_forecast, train_models


def _stale(site_id: int, days: int) -> bool:
    m = repo.load_model(site_id, "solar")
    if m is None:
        return True
    ts = pd.Timestamp(m["trained_at"])
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
    return ts < datetime.now(timezone.utc) - timedelta(days=days)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retrain-older-than", type=int, default=0, help="retrain models older than N days (0 = never)")
    args = ap.parse_args()

    init_db()
    try:                               # keeps the demo account's data up to yesterday
        from db.seed import seed_demo
        print(f"demo account: {seed_demo()['status']}")
    except Exception as exc:  # noqa: BLE001
        print(f"demo account: refresh failed ({exc})", file=sys.stderr)
    sites = repo.list_sites()
    ok = failed = 0
    for site in sites:
        try:
            if args.retrain_older_than and repo.readings_summary(site["id"])["rows"] and _stale(site["id"], args.retrain_older_than):
                report = train_models(site)
                print(f"site {site['id']}: retrained {({k: 'error' if 'error' in v else 'ok' for k, v in report.items()})}")
            out = run_forecast(site, save=True)
            m = out["month"]
            print(f"site {site['id']}: {out['daily']['pv'].sum():.1f} kWh PV next 7 days, "
                  f"month billed ~{m['billed_kwh']:.0f} kWh, weather={out['weather_source']}")
            ok += 1
        except Exception as exc:  # noqa: BLE001 - one bad site must not stop the rest
            print(f"site {site['id']}: FAILED {exc}", file=sys.stderr)
            failed += 1
    print(f"done: {ok} ok, {failed} failed, {len(sites)} sites")
    return 1 if sites and ok == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
