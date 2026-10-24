"""Versioned compensation rules and the monthly quantity-compensation calculation."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

VERSIONS_DIR = Path(__file__).resolve().parent / "versions"
STAGED_DIR = Path(__file__).resolve().parent / "staged"

CUSTOMER_TYPES = {
    "individual": "Persoană fizică",
    "company": "Companie",
    "public_institution": "Instituție publică",
}


def _as_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass
class Rule:
    id: str
    version: int
    effective_from: date
    title: str
    applies_to: dict
    params: dict
    source: str | None = None
    source_url: str | None = None
    summary_ro: str | None = None
    verified: bool = False
    demo: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        """Accepts a YAML document or a row from the rules table."""
        params = d.get("params") or d.get("params_json") or {}
        return cls(
            id=d["id"],
            version=int(d["version"]),
            effective_from=_as_date(d["effective_from"]),
            title=d.get("title") or d["id"],
            applies_to=d.get("applies_to") or d.get("applies_to_json") or {},
            params=params,
            source=d.get("source"),
            source_url=d.get("source_url"),
            summary_ro=(d.get("summary_ro") or d.get("summary") or "").strip(),
            verified=bool(d.get("verified", False)),
            demo=bool(d.get("demo", False) or "DEMO" in str(d["id"])),
        )

    def applies(self, customer_type: str, kw: float | None) -> bool:
        types = self.applies_to.get("customer_types")
        if types and customer_type not in types:
            return False
        max_kw = self.applies_to.get("max_kw")
        if max_kw is not None and kw is not None and kw > max_kw:
            return False
        return True

    @property
    def label(self) -> str:
        return f"{self.title} (v{self.version}, în vigoare din {self.effective_from:%d.%m.%Y})"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "version": self.version, "effective_from": self.effective_from.isoformat(),
            "title": self.title, "applies_to": self.applies_to, "params": self.params,
            "source": self.source, "source_url": self.source_url, "summary_ro": self.summary_ro,
            "verified": self.verified, "demo": self.demo,
        }


def load_rule_file(path: Path) -> Rule:
    with open(path, encoding="utf-8") as f:
        return Rule.from_dict(yaml.safe_load(f))


def load_rules(directory: Path = VERSIONS_DIR) -> list[Rule]:
    rules = [load_rule_file(p) for p in sorted(directory.glob("*.yaml"))]
    return sorted(rules, key=lambda r: (r.effective_from, r.version))


def rule_for(on: date, customer_type: str, kw: float | None, rules: list[Rule]) -> Rule | None:
    """The newest rule in force on `on` that applies to this customer."""
    candidates = [r for r in rules if r.effective_from <= on and r.applies(customer_type, kw)]
    return max(candidates, key=lambda r: (r.effective_from, r.version)) if candidates else None


def previous_rule(rule: Rule, customer_type: str, kw: float | None, rules: list[Rule]) -> Rule | None:
    # kW is ignored on purpose: an older rule that excluded this system is still "the rule before".
    older = [r for r in rules if (r.effective_from, r.version) < (rule.effective_from, rule.version)
             and r.applies(customer_type, None)]
    return max(older, key=lambda r: (r.effective_from, r.version)) if older else None


@dataclass
class CompensationResult:
    consumed_kwh: float
    delivered_kwh: float
    carried_in_kwh: float
    compensated_kwh: float
    billed_kwh: float
    new_carryover_kwh: float
    eligible: bool
    rule_id: str | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def compute_compensation(period: tuple[date, date], consumed_kwh: float, delivered_kwh: float,
                         carried_over_kwh: float, rule: Rule | None,
                         system_kw: float | None = None) -> CompensationResult:
    """Monthly quantity compensation: delivered kWh (plus credit carried over) offset consumed kWh 1:1.

    Returns the expected compensated kWh, the kWh left to pay for and the new carried-over credit.
    Open questions (expiry of surplus, network tariffs on compensated kWh) are reported in `notes`
    instead of being guessed.
    """
    consumed = max(0.0, float(consumed_kwh or 0))
    delivered = max(0.0, float(delivered_kwh or 0))
    carried = max(0.0, float(carried_over_kwh or 0))
    notes: list[str] = []

    if rule is None:
        return CompensationResult(consumed, delivered, carried, 0.0, consumed, carried, False, None,
                                  ["Nu există o regulă de compensare pentru această perioadă."])

    p = rule.params
    period_end = _as_date(period[1])
    until = _as_date(p.get("quantity_compensation_until"))
    max_kw = p.get("quantity_compensation_max_kw")

    eligible = p.get("compensation_type") == "quantity"
    if until and period_end and period_end > until:
        eligible = False
        notes.append(f"Compensarea cantitativă este disponibilă doar până la {until:%d.%m.%Y}.")
    if max_kw is not None and system_kw is not None and system_kw > max_kw:
        eligible = False
        notes.append(f"Instalația de {system_kw:g} kW depășește limita de {max_kw:g} kW pentru compensare cantitativă.")

    if not eligible:
        return CompensationResult(consumed, delivered, carried, 0.0, consumed, carried, False, rule.id, notes)

    available = delivered + carried
    compensated = min(consumed, available)
    billed = consumed - compensated
    new_carry = available - compensated

    if p.get("carryover_months") is None:
        notes.append("Cât timp rămâne valabil surplusul reportat nu este încă verificat (metodologia ANRE).")
    else:
        notes.append(f"Surplusul reportat expiră după {p['carryover_months']} luni; vechimea lui nu este urmărită aici.")
    if p.get("network_tariffs_on_compensated") is None:
        notes.append("Dacă tarifele de rețea se aplică și energiei compensate nu este încă verificat.")

    return CompensationResult(consumed, delivered, carried, round(compensated, 3), round(billed, 3),
                              round(new_carry, 3), True, rule.id, notes)


def monthly_balance(months: list[dict], customer_type: str, system_kw: float | None, rules: list[Rule],
                    start_carryover_kwh: float = 0.0) -> list[dict]:
    """Chain compute_compensation over months: [{'start': date, 'end': date, 'consumed': x, 'delivered': y}]."""
    carry = start_carryover_kwh
    out = []
    for mth in months:
        rule = rule_for(_as_date(mth["end"]), customer_type, system_kw, rules)
        res = compute_compensation((mth["start"], mth["end"]), mth["consumed"], mth["delivered"], carry, rule, system_kw)
        carry = res.new_carryover_kwh
        out.append({**mth, **res.to_dict()})
    return out


def is_number(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))
