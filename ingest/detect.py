"""Read an inverter export (CSV, XLSX, JSON) and guess which column is which."""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata

import pandas as pd

from ingest import mappers

ROLES = {
    "timestamp": "Data și ora",
    "pv": "Producție PV",
    "load": "Consum casă",
    "grid_import": "Import din rețea",
    "grid_export": "Export în rețea",
    "batt_charge": "Încărcare baterie",
    "batt_discharge": "Descărcare baterie",
    "soc": "Nivel baterie (SOC)",
}
ENERGY_ROLES = ["pv", "load", "grid_import", "grid_export", "batt_charge", "batt_discharge"]
UNITS = ["kWh", "Wh", "kW", "W", "%"]

# Checked in this order: specific phrases before generic words ("grid consumption" is an import).
KEYWORDS = [
    ("timestamp", ["timestamp", "datetime", "date time", "data si ora", "data/ora", "time", "data", "date", "ora"]),
    ("grid_import", ["import", "from grid", "purchased", "bought", "buy", "grid consumption", "cumparat",
                     "achizitionat", "din retea"]),
    ("grid_export", ["export", "to grid", "feed in", "feed-in", "feedin", "sell", "injectat", "livrat", "in retea"]),
    ("batt_discharge", ["discharg", "descarcare"]),
    ("batt_charge", ["charg", "incarcare"]),
    ("soc", ["soc", "state of charge", "battery level", "nivel baterie"]),
    ("pv", ["pv", "solar", "yield", "production", "productie", "generation", "generare", "producere"]),
    ("load", ["load", "consumption", "consum", "house", "home", "casa", "self use"]),
]


def plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower()).strip()


def _sniff_sep(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {s: sample.count(s) for s in (";", ",", "\t")}
        return max(counts, key=counts.get)


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """All cells as strings; numbers are parsed later with the chosen units."""
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        raw = pd.read_excel(io.BytesIO(data), header=None, dtype=str)
        return _promote_header(raw)
    if name.endswith(".json"):
        obj = json.loads(data.decode("utf-8-sig"))
        if isinstance(obj, dict):
            lists = [v for v in obj.values() if isinstance(v, list)]
            obj = lists[0] if lists else [obj]
        return pd.json_normalize(obj).astype(str)
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    sep = _sniff_sep("\n".join(lines[:50]))
    # skip metadata lines above the header: the header is the first line with the full column count
    counts = [ln.count(sep) for ln in lines[:30]]
    width = max(counts) if counts else 0
    skip = next((i for i, c in enumerate(counts) if c == width), 0)
    return pd.read_csv(io.StringIO("\n".join(lines[skip:])), sep=sep, dtype=str, keep_default_na=False)


def _promote_header(raw: pd.DataFrame) -> pd.DataFrame:
    filled = raw.notna().sum(axis=1)
    hdr = int((filled >= filled.max() * 0.8).idxmax())
    df = raw.iloc[hdr + 1:].reset_index(drop=True)
    df.columns = [str(c) if pd.notna(c) else f"col{i}" for i, c in enumerate(raw.iloc[hdr])]
    return df.fillna("")


def guess_unit(column: str) -> str:
    c = plain(column)
    for pat, unit in ((r"\bkwh\b", "kWh"), (r"\bwh\b", "Wh"), (r"\bkw\b", "kW"), (r"\bw\b", "W"), (r"%", "%")):
        if re.search(pat, c):
            return unit
    return "kWh"


def guess_mapping(df: pd.DataFrame) -> dict:
    """Returns {"format": name or None, "mapping": role->column, "units": role->unit, "kind", "label", "timezone"}."""
    known = mappers.match(list(df.columns))
    if known:
        return {"format": known["name"], "mapping": dict(known["mapping"]), "units": dict(known["units"]),
                "kind": known["kind"], "label": known["label"], "timezone": known["timezone"],
                "dayfirst": known["dayfirst"]}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for role, words in KEYWORDS:
        for col in df.columns:
            if col in used:
                continue
            c = plain(col)
            if any(w in c for w in words):
                if role == "batt_charge" and "discharg" in c:
                    continue
                mapping[role] = col
                used.add(col)
                break
    units = {r: guess_unit(mapping[r]) for r in mapping if r != "timestamp"}
    if "soc" in units:
        units["soc"] = "%"
    kinds = {r: ("cumulative" if units.get(r) in ("kWh", "Wh") and _looks_cumulative(df[mapping[r]]) else "interval")
             for r in ENERGY_ROLES if r in mapping}
    return {"format": None, "mapping": mapping, "units": units, "kind": kinds, "label": "start",
            "timezone": "Europe/Bucharest", "dayfirst": True}


def _looks_cumulative(col: pd.Series) -> bool:
    from ingest.normalize import to_number

    v = to_number(col).dropna()
    if len(v) < 10:
        return False
    # interval energy drops to ~0 every night; a meter counter only ever goes up (resets aside)
    rising = (v.diff().dropna() >= 0).mean()
    return bool(rising > 0.99 and v.iloc[-1] > v.iloc[0] and v.nunique() > 3)
