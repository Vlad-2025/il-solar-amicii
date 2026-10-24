"""Romanian bill vocabulary. Verify every pattern against real bills and extend per supplier.

Matching runs on text with diacritics removed and lower-cased (ș/ş -> s, ț/ţ -> t, ă/â -> a, î -> i).
"""
from __future__ import annotations

import re
import unicodedata

# Order matters: totals before VAT ("Total fără TVA" must not count as VAT), specific before generic.
LINE_PATTERNS: list[tuple[str, list[str]]] = [
    ("total", [r"total\s+de\s+plata", r"total\s+factura\b", r"suma\s+de\s+plata"]),
    ("subtotal", [r"total\s+(fara|f\.?)\s*tva", r"valoare\s+fara\s+tva", r"\bsubtotal\b", r"baza\s+de\s+impozitare"]),
    ("vat", [r"\btva\b", r"taxa\s+pe\s+valoarea\s+adaugata"]),
    ("energy_compensated", [r"energie\s+(electrica\s+)?(activa\s+)?compensata", r"cantitate\s+compensata"]),
    ("carryover", [r"cantitate\s+reportata", r"energie\s+reportata", r"\bsold\s+(de\s+)?energie"]),
    ("energy_delivered", [r"energie\s+(electrica\s+)?(activa\s+)?(livrata|produsa|injectata)"]),
    ("energy_billed", [r"energie\s+(electrica\s+)?(activa\s+)?facturata", r"energie\s+de\s+plata"]),
    ("energy_consumed", [r"energie\s+(electrica\s+)?(activa\s+)?consumata", r"consum\s+(de\s+)?energie\s+activa"]),
    ("distribution_tariff", [r"tarif\w*\s+(de\s+)?distributie", r"servic\w*\s+(de\s+)?distributie"]),
    ("transport_tariff", [r"tarif\w*\s+(de\s+)?transport", r"\btransport\s+(si|-)\s*introducere"]),
    ("system_services", [r"servic\w*\s+(de\s+)?sistem"]),
    ("green_certificates", [r"certificat\w*\s+verzi"]),
    ("cogeneration", [r"cogenerare"]),
    ("excise", [r"acciz"]),
]
COMPILED = [(t, [re.compile(p) for p in pats]) for t, pats in LINE_PATTERNS]

# Thousands separators: dot or non-breaking space. Plain spaces are NOT accepted, or two numbers in a
# table row ("21 508") would merge into one.
NUM = r"-?\d{1,3}(?:[. ]\d{3})+(?:,\d+)?|-?\d+(?:[.,]\d+)?"
DATE = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"

PERIOD_RE = re.compile(rf"perioad\w*\s+(?:de\s+)?(?:facturare|consum)\s*:?\s*({DATE})\s*(?:-|–|—|pana\s+la|la)\s*({DATE})")
POD_RE = re.compile(r"(?:cod\s+loc\s+(?:de\s+)?consum|cod\s+pod|\bpod\b|\bnlc\b)\s*(?:\(pod\))?\s*:?\s*([a-z0-9]{8,})")
INDEX_OLD_RE = re.compile(rf"index\s+(?:vechi|anterior|initial)\s*:?\s*({NUM})")
INDEX_NEW_RE = re.compile(rf"index\s+(?:nou|actual|curent|final)\s*:?\s*({NUM})")
VAT_RATE_RE = re.compile(r"tva\s*\(?\s*(\d{1,2}(?:[.,]\d+)?)\s*%")
QTY_RE = re.compile(rf"({NUM})\s*kwh(?!\s*/)")
PRICE_RE = re.compile(rf"({NUM})\s*lei\s*/\s*kwh")
NUM_RE = re.compile(NUM)


def plain(text: str) -> str:
    t = (text or "").replace("ş", "ș").replace("ţ", "ț").replace("Ş", "Ș").replace("Ţ", "Ț")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[ \t]+", " ", t.lower())


def parse_ro_number(s: str | None) -> float | None:
    """1.234,56 -> 1234.56 · 1234,56 -> 1234.56 · 12.345 -> 12345 (thousands) · 0,6800 -> 0.68"""
    if s is None:
        return None
    s = s.strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def classify(line_plain: str) -> str | None:
    for line_type, pats in COMPILED:
        if any(p.search(line_plain) for p in pats):
            return line_type
    return None
