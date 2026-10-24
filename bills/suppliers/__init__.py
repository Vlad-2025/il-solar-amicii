"""Supplier detection and per-supplier extraction templates.

A template is a module with `extract(text, plain_text) -> dict` that overrides any field the generic
extractor gets wrong for that supplier's layout. Start with the 2–3 suppliers interviewees use:
collect one real bill each, then add anchors (label text + regex) in a module next to demo.py.
Identify by name here; add the supplier's tax ID (CUI) only after reading it off a real bill.
"""
from __future__ import annotations

from bills.suppliers import demo, generic

SUPPLIERS = [
    # name shown in the app, keywords searched in the plain (lower-case, no diacritics) text, template
    {"name": "Furnizor Demo SA", "keywords": ["furnizor demo"], "template": demo},
    {"name": "Electrica Furnizare", "keywords": ["electrica furnizare"], "template": generic},
    {"name": "PPC Energie (fost Enel Energie)", "keywords": ["ppc energie", "enel energie"], "template": generic},
    {"name": "E.ON Energie România", "keywords": ["e.on energie", "eon energie"], "template": generic},
    {"name": "Hidroelectrica", "keywords": ["hidroelectrica"], "template": generic},
    {"name": "ENGIE România", "keywords": ["engie romania"], "template": generic},
    {"name": "Premier Energy", "keywords": ["premier energy"], "template": generic},
]


def detect(plain_text: str) -> dict | None:
    head = plain_text[:3000]
    for s in SUPPLIERS:
        if any(k in head for k in s["keywords"]):
            return s
    for s in SUPPLIERS:
        if any(k in plain_text for k in s["keywords"]):
            return s
    return None


def names() -> list[str]:
    return [s["name"] for s in SUPPLIERS] + ["Alt furnizor"]
