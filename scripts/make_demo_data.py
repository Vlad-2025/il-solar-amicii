"""Write data/demo/demo_inverter_export.csv: the demo household as a downloadable inverter export.

    python scripts/make_demo_data.py                # tries real Bucharest weather (Open-Meteo), else synthetic
    python scripts/make_demo_data.py --synthetic    # always synthetic

With real weather, a user who uploads this file and trains gets realistic accuracy numbers, because the
app downloads the same historical weather. Run it on a machine with internet before the pitch.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import weather as wx  # noqa: E402
from ingest.demo import DEMO_SITE, DEMO_START, generate, to_vendor_csv  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    args = ap.parse_args()
    end = date.fromisoformat(args.end)

    real = None
    if not args.synthetic:
        try:
            real = wx.fetch_historical(DEMO_SITE["lat"], DEMO_SITE["lon"], DEMO_START.date(), end)
            print(f"real weather: {len(real)} hours from Open-Meteo")
        except wx.WeatherUnavailable as exc:
            print(f"Open-Meteo unavailable ({exc}); using synthetic weather")
    readings, _ = generate(end, weather=real)
    out = ROOT / "data" / "demo" / "demo_inverter_export.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_vendor_csv(readings), encoding="utf-8")
    print(f"{len(readings)} hours, PV {readings['pv_kwh'].sum():.0f} kWh -> {out} "
          f"({'real' if real is not None else 'synthetic'} weather)")


if __name__ == "__main__":
    main()
