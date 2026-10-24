"""Pre-filled request to the supplier, with the evidence. The user reviews and sends it themselves."""
from __future__ import annotations

from datetime import date

from rules.explain import kwh


def draft(bill: dict, checks: list[dict], site: dict, user_email: str, name: str = "[Numele dumneavoastră]") -> dict:
    flagged = [c for c in checks if c.get("severity") == "worth_checking"]
    period = (f"{bill['period_start']:%d.%m.%Y} – {bill['period_end']:%d.%m.%Y}"
              if bill.get("period_start") and bill.get("period_end") else "[perioada]")
    supplier = bill.get("supplier") or site.get("supplier") or "[furnizor]"
    pod = bill.get("pod") or "[cod loc de consum / POD]"
    subject = f"Solicitare de verificare a facturii pentru perioada {period} – POD {pod}"

    evidence = "\n".join(f"  {i}. {c['message']}" for i, c in enumerate(flagged, 1)) or \
        "  1. [descrieți diferența constatată]"
    lines = {ln["line_type"]: ln for ln in bill.get("lines", [])}
    facts = []
    for t, label in (("energy_consumed", "Energie consumată"), ("energy_delivered", "Energie livrată"),
                     ("energy_compensated", "Energie compensată"), ("carryover", "Cantitate reportată")):
        if t in lines and lines[t].get("qty_kwh") is not None:
            facts.append(f"  - {label}: {kwh(lines[t]['qty_kwh'])}")
    body = f"""Către: {supplier}
Subiect: {subject}

Bună ziua,

Sunt prosumator, cu o instalație fotovoltaică de {site.get('kwp') or 0:g} kWp, la locul de consum cu codul {pod}.
Vă rog să verificați factura pentru perioada {period}. Conform datelor înregistrate de invertorul meu
și calculului de compensare cantitativă lunară (Legea 160/2026), am constatat următoarele:

{evidence}

Valorile de pe factură:
{chr(10).join(facts) or '  - [valori]'}

Știu că invertorul nu este contorul oficial. Vă rog să verificați citirile contorului (inclusiv registrul
de energie livrată), modul de calcul al compensării și al cantității reportate, și să îmi comunicați
răspunsul în scris. Pot trimite exportul de date de la invertor, la cerere.

Vă mulțumesc,
{name}
E-mail: {user_email}
Data: {date.today():%d.%m.%Y}
"""
    return {"subject": subject, "body": body, "flagged": len(flagged)}
