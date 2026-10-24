"""Create or refresh the demo account (demo@prosumer.demo) in the database DATABASE_URL points to.

    python scripts/seed_demo.py           # only if missing or stale
    python scripts/seed_demo.py --force   # regenerate data up to yesterday and retrain
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.seed import seed_demo  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    res = seed_demo(force=ap.parse_args().force)
    print(res)
