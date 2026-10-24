"""Known export formats, recognised by their header names.

Each detector must be built from a REAL sample export. Only the demo format is here so far; add
Huawei FusionSolar, SolarEdge, Fronius Solar.web and Growatt/Deye (Solarman) once interviewees
share an export: copy the header row exactly, map it, and add a test with the sample file.
"""
from __future__ import annotations

KNOWN_FORMATS: list[dict] = [
    {
        "name": "Export demo (Prosumer Assistant)",
        "headers": ["Data si ora", "Productie PV (kWh)", "Consum casa (kWh)", "Import retea (kWh)",
                    "Export retea (kWh)", "Incarcare baterie (kWh)", "Descarcare baterie (kWh)", "SOC baterie (%)"],
        "mapping": {
            "timestamp": "Data si ora", "pv": "Productie PV (kWh)", "load": "Consum casa (kWh)",
            "grid_import": "Import retea (kWh)", "grid_export": "Export retea (kWh)",
            "batt_charge": "Incarcare baterie (kWh)", "batt_discharge": "Descarcare baterie (kWh)",
            "soc": "SOC baterie (%)",
        },
        "units": {"pv": "kWh", "load": "kWh", "grid_import": "kWh", "grid_export": "kWh",
                  "batt_charge": "kWh", "batt_discharge": "kWh", "soc": "%"},
        "kind": "interval",
        "label": "start",
        "timezone": "Europe/Bucharest",
        "dayfirst": True,
    },
]


def match(columns: list[str]) -> dict | None:
    cols = {c.strip() for c in columns}
    for fmt in KNOWN_FORMATS:
        if set(fmt["headers"]) <= cols:
            return fmt
    return None
