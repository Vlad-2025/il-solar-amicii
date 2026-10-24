"""Runs when a file under rules/versions/ changes on main: loads every version into the database and
sends each affected user a personalised ntfy push for versions that are new.

    python -m jobs.rule_alerts
    python -m jobs.rule_alerts --no-notify     # load rules only
"""
from __future__ import annotations

import argparse

from alerts.rules_publish import sync_from_files
from db.client import init_db


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()
    init_db()
    for res in sync_from_files(notify=not args.no_notify):
        status = "NEW" if res["new"] else "unchanged"
        delivered = sum(1 for r in res["notified"] if r["delivered"])
        print(f"{res['rule_id']}: {status}; notified {len(res['notified'])} users ({delivered} delivered by ntfy)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
