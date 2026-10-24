from datetime import date
from pathlib import Path

import pytest

from bills import ocr
from bills.check import check_bill
from bills.complaint import draft
from bills.parse import parse_bill
from bills.suppliers import generic
from bills.terms_ro import parse_ro_number
from bills.validate import validate
from ingest.demo import DEMO_SITE
from rules.compensation import load_rules, rule_for

DEMO = Path(__file__).resolve().parents[1] / "data" / "demo"


def _q(fields, t, key="qty_kwh"):
    return next(ln[key] for ln in fields["lines"] if ln["line_type"] == t)


@pytest.mark.parametrize("s,v", [("1.234,56", 1234.56), ("0,6800", 0.68), ("12.345", 12345.0), ("21.10", 21.1),
                                 ("7,62", 7.62), ("1,234.56", 1234.56), ("", None)])
def test_ro_numbers(s, v):
    assert parse_ro_number(s) == v


def test_demo_pdf_parses_completely():
    f = parse_bill((DEMO / "factura_demo_2026-09.pdf").read_bytes(), "f.pdf")
    assert f["parse_method"] == "pdf_text" and f["supplier"] == "Furnizor Demo SA"
    assert (f["period_start"], f["period_end"]) == (date(2026, 9, 1), date(2026, 9, 30))
    assert f["pod"] == "RO000E000DEMO0001" and f["vat_rate"] == 21 and f["total_lei"] == 7.62
    assert _q(f, "energy_consumed") == 21 and _q(f, "energy_delivered") == 450
    assert _q(f, "distribution_tariff", "amount_lei") == 4.51
    assert all(c["ok"] for c in f["validation"]) and len(f["validation"]) == 5
    assert f["confidence"] >= 0.9 and not f["warnings"]


@pytest.mark.skipif(not ocr.tesseract_available(), reason="Tesseract not installed")
def test_demo_photo_parses_with_ocr():
    f = parse_bill((DEMO / "factura_demo_2026-09_poza.jpg").read_bytes(), "p.jpg")
    assert f["parse_method"] == "ocr" and f["ocr_confidence"] > 60
    assert f["total_lei"] == 7.62 and _q(f, "energy_delivered") == 450
    assert all(c["ok"] for c in f["validation"] if c["name"] in ("sum_lines", "vat", "total"))


def test_validation_catches_a_wrong_total():
    text = """Perioada de facturare: 01.09.2026 - 30.09.2026
Tarif de distribuție 21 kWh 0,2150 lei/kWh 4,51
Acciză 21 kWh 0,0055 lei/kWh 0,12
Total fără TVA 4,63
TVA 21% 0,97
Total de plată 9,99 lei"""
    checks = {c["name"]: c["ok"] for c in validate(generic.extract(text))}
    assert checks["sum_lines"] and checks["vat"] and not checks["total"]


def test_check_flags_delivered_difference_and_matches_compensation(demo_data):
    readings, _ = demo_data
    f = parse_bill((DEMO / "factura_demo_2026-09.pdf").read_bytes(), "f.pdf")
    rule = rule_for(f["period_end"], "individual", 6, load_rules())
    checks = {c["check_type"]: c for c in check_bill(f, readings, rule, None, 6)}
    assert checks["delivered_vs_inverter"]["severity"] == "worth_checking"
    assert checks["delivered_vs_inverter"]["diff_pct"] == pytest.approx(-11.5, abs=0.5)
    assert checks["consumed_vs_inverter"]["severity"] == "ok"
    assert checks["compensation"]["severity"] == "ok"
    assert "overcharged" not in str(checks).lower() and "taxat în plus" not in str(checks)
    letter = draft(f, list(checks.values()), DEMO_SITE, "a@b.ro")
    assert letter["flagged"] == 1 and "RO000E000DEMO0001" in letter["body"] and "6 kWp" in letter["body"]


def test_check_without_inverter_data_is_informative():
    import pandas as pd
    f = {"period_start": date(2026, 9, 1), "period_end": date(2026, 9, 30),
         "lines": [{"line_type": "energy_delivered", "qty_kwh": 100}]}
    checks = check_bill(f, pd.DataFrame(columns=["grid_export_kwh", "grid_import_kwh"]), None, None, 6)
    assert checks[0]["check_type"] == "coverage" and checks[0]["severity"] == "info"
