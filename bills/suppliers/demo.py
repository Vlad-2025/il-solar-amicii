"""Template for the fictional demo supplier, and the pattern to copy for real suppliers:
run the generic extractor, then fix the fields this layout is known to break, using anchors."""
from __future__ import annotations

import re

from bills import terms_ro as T
from bills.suppliers import generic

# Anchor: the demo bill prints "Factura nr. DEMO-0001 din 05.10.2026"
INVOICE_RE = re.compile(r"factura\s+nr\.?\s*([a-z0-9-]+)\s+din\s+(" + T.DATE + ")")


def extract(text: str, plain_text: str | None = None) -> dict:
    plain_text = plain_text if plain_text is not None else T.plain(text)
    fields = generic.extract(text, plain_text)
    m = INVOICE_RE.search(plain_text)
    if m:
        fields["invoice_no"] = m.group(1).upper()
        fields["invoice_date"] = generic._date(m.group(2))
    return fields
