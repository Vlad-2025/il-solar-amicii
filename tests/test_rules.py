from datetime import date

import pytest

from rules.compensation import STAGED_DIR, compute_compensation, load_rule_file, load_rules, monthly_balance, previous_rule, rule_for
from rules.explain import change_note, energy_balance, explain_line, why_pay_note

RULES = load_rules()
SEPT = (date(2026, 9, 1), date(2026, 9, 30))


def test_rule_files_are_consistent():
    ids = [r.id for r in RULES]
    assert len(ids) == len(set(ids))
    assert [r.version for r in RULES] == sorted(r.version for r in RULES)
    for r in RULES:
        assert r.params["compensation_type"] == "quantity"
        assert r.summary_ro
        assert not r.demo
    assert load_rule_file(STAGED_DIR / "demo_next_version.yaml").demo


def test_rule_in_force_by_date_and_size():
    assert rule_for(date(2026, 9, 30), "individual", 6, RULES).version == 2
    assert rule_for(date(2026, 7, 1), "individual", 6, RULES).version == 1
    assert rule_for(date(2026, 7, 1), "company", 300, RULES) is None      # 300 kW excluded before Law 160
    assert rule_for(date(2026, 9, 1), "company", 300, RULES).version == 2


def test_surplus_month_carries_over():
    r = compute_compensation(SEPT, 312, 498, 40, rule_for(SEPT[1], "individual", 6, RULES), 6)
    assert (r.compensated_kwh, r.billed_kwh, r.new_carryover_kwh) == (312, 0, 226)
    assert r.eligible and r.notes


def test_deficit_month_uses_carryover_then_bills():
    r = compute_compensation(SEPT, 500, 200, 100, rule_for(SEPT[1], "individual", 6, RULES), 6)
    assert (r.compensated_kwh, r.billed_kwh, r.new_carryover_kwh) == (300, 200, 0)


@pytest.mark.parametrize("period,kw", [((date(2031, 1, 1), date(2031, 1, 31)), 6), (SEPT, 450)])
def test_not_eligible(period, kw):
    rule = rule_for(date(2026, 9, 30), "company", 300, RULES)
    r = compute_compensation(period, 100, 300, 0, rule, kw)
    assert not r.eligible and r.billed_kwh == 100 and r.compensated_kwh == 0


def test_monthly_chain():
    months = [{"start": date(2026, 8, 1), "end": date(2026, 8, 31), "consumed": 100, "delivered": 300},
              {"start": date(2026, 9, 1), "end": date(2026, 9, 30), "consumed": 400, "delivered": 100}]
    out = monthly_balance(months, "individual", 6, RULES)
    assert out[0]["new_carryover_kwh"] == 200
    assert out[1]["billed_kwh"] == 100 and out[1]["new_carryover_kwh"] == 0


def test_change_note_is_personal():
    new = rule_for(date(2026, 9, 1), "individual", 6, RULES)
    small = change_note(previous_rule(new, "individual", 6, RULES), new, "individual", 6)
    assert "nu se schimbă" in small["impact"] and "200 kW → 400 kW" in small["message"]
    big = change_note(previous_rule(new, "company", 300, RULES), new, "company", 300)
    assert "fără compensare cantitativă → compensare cantitativă" in big["impact"]
    assert "regularizarea financiară" in big["impact"]


def test_explanations_and_balance():
    lines = [{"line_type": "energy_consumed", "qty_kwh": 21}, {"line_type": "energy_delivered", "qty_kwh": 450},
             {"line_type": "energy_compensated", "qty_kwh": 21}, {"line_type": "total", "amount_lei": 7.62}]
    bal = energy_balance(lines)
    assert bal["billed"] == 0 and "21 kWh" in bal["sentence"]
    assert why_pay_note(lines)
    assert "7,62 lei" in explain_line(lines[3])
    assert "1.234,50 lei" in explain_line({"line_type": "total", "amount_lei": 1234.5})
