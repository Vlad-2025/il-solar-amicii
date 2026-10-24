"""Generate the demo bill (PDF + a phone-photo version) for the fictional "Furnizor Demo SA".

Numbers come from the demo household's September 2026 data. Delivered energy is printed 12% below
what the inverter measured, so the bill check has something to flag on stage.
Every page says it is a fictional demonstration document, not a fiscal one.

    pip install reportlab   # dev only
    python scripts/make_demo_bill.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from reportlab.lib.colors import Color, HexColor  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from ingest.demo import generate  # noqa: E402

OUT = ROOT / "data" / "demo"
FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts"), Path("C:/Windows/Fonts")]


def register_fonts() -> tuple[str, str]:
    for d in FONT_DIRS:
        reg, bold = d / "DejaVuSans.ttf", d / "DejaVuSans-Bold.ttf"
        if reg.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("DV", str(reg)))
            pdfmetrics.registerFont(TTFont("DVB", str(bold)))
            return "DV", "DVB"
    raise SystemExit("DejaVu Sans not found (needed for ș/ț). Install fonts-dejavu.")


def ro(x: float, d: int = 2) -> str:
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def bill_numbers() -> dict:
    readings, _ = generate(date(2026, 9, 30))
    sep = readings.tz_convert("Europe/Bucharest").loc["2026-09"]
    consumed = round(float(sep["grid_import_kwh"].sum()))
    inverter_export = float(sep["grid_export_kwh"].sum())
    delivered = round(inverter_export * 0.88)
    carried_in = 180
    compensated = min(consumed, delivered + carried_in)
    billed = consumed - compensated
    carry_out = delivered + carried_in - compensated
    tariffs = [
        ("Tarif de distribuție", 0.2150), ("Tarif de transport (TG + TL)", 0.0310),
        ("Servicii de sistem", 0.0062), ("Certificate verzi", 0.0395),
        ("Contribuție cogenerare", 0.0029), ("Acciză", 0.0055),
    ]
    money = [("Energie activă facturată", billed, 0.6800, round(billed * 0.68, 2))]
    money += [(label, consumed, p, round(consumed * p, 2)) for label, p in tariffs]
    subtotal = round(sum(m[3] for m in money), 2)
    vat = round(subtotal * 0.21, 2)
    return {"consumed": consumed, "delivered": delivered, "inverter_export": inverter_export,
            "carried_in": carried_in, "compensated": compensated, "carry_out": carry_out,
            "money": money, "subtotal": subtotal, "vat": vat, "total": round(subtotal + vat, 2),
            "index_old": 12345, "index_new": 12345 + consumed}


def make_pdf(path: Path, n: dict) -> None:
    reg, bold = register_fonts()
    W, H = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Factură DEMO – Furnizor Demo SA (document fictiv)")

    c.saveState()                                           # watermark
    c.setFillColor(Color(0.85, 0.85, 0.85, alpha=0.5))
    c.setFont(bold, 40)
    c.translate(W / 2, H / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "DOCUMENT DEMONSTRATIV")
    c.restoreState()

    c.setFillColor(HexColor("#1d4e89"))
    c.rect(0, H - 70, W, 70, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont(bold, 18)
    c.drawString(40, H - 42, "FURNIZOR DEMO SA")
    c.setFont(reg, 9)
    c.drawString(40, H - 58, "Furnizor fictiv, folosit doar pentru demonstrația aplicației Prosumer Assistant")

    y = H - 100
    c.setFillColor(HexColor("#000000"))
    c.setFont(bold, 13)
    c.drawString(40, y, "Factură energie electrică – prosumator")
    c.setFont(reg, 10)
    rows = [
        "Factura nr. DEMO-0001 din 05.10.2026",
        "Client: Gospodărie Demo, Str. Exemplu nr. 1, București",
        "Cod loc de consum (POD): RO000E000DEMO0001",
        "Perioada de facturare: 01.09.2026 - 30.09.2026",
        f"Index vechi: {ro(n['index_old'], 0)}     Index nou: {ro(n['index_new'], 0)}",
    ]
    for r in rows:
        y -= 16
        c.drawString(40, y, r)

    y -= 30
    c.setFont(bold, 11)
    c.drawString(40, y, "Situația energiei")
    c.setFont(reg, 10)
    for label, val in (("Energie activă consumată", n["consumed"]), ("Energie activă livrată (produsă)", n["delivered"]),
                       ("Energie compensată", n["compensated"]), ("Cantitate reportată", n["carry_out"])):
        y -= 16
        c.drawString(40, y, label)
        c.drawRightString(330, y, f"{ro(val, 0)} kWh")

    y -= 30
    c.setFont(bold, 11)
    c.drawString(40, y, "Detalii de facturare")
    y -= 16
    c.setFont(bold, 9)
    for x, t in ((40, "Descriere"), (330, "Cantitate"), (440, "Preț unitar"), (555, "Valoare (lei)")):
        (c.drawRightString if x > 40 else c.drawString)(x, y, t)
    c.line(40, y - 4, 555, y - 4)
    c.setFont(reg, 10)
    for label, qty, price, amount in n["money"]:
        y -= 17
        c.drawString(40, y, label)
        c.drawRightString(330, y, f"{ro(qty, 0)} kWh")
        c.drawRightString(440, y, f"{ro(price, 4)} lei/kWh")
        c.drawRightString(555, y, ro(amount))
    c.line(40, y - 6, 555, y - 6)
    y -= 22
    c.setFont(bold, 10)
    for label, val in (("Total fără TVA", n["subtotal"]), ("TVA 21%", n["vat"])):
        c.drawString(330, y, label)
        c.drawRightString(555, y, ro(val))
        y -= 17
    c.setFont(bold, 13)
    c.drawString(330, y - 4, "Total de plată")
    c.drawRightString(555, y - 4, f"{ro(n['total'])} lei")

    c.setFont(reg, 8)
    c.setFillColor(HexColor("#555555"))
    c.drawString(40, 40, "Factură fictivă pentru demonstrație. Nu este un document fiscal. Datele clientului sunt inventate.")
    c.showPage()
    c.save()


def make_photo(pdf_path: Path, out: Path) -> None:
    """Simulate a phone photo: slight rotation, uneven light, blur, JPEG."""
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(str(pdf_path))[0]
    img = cv2.cvtColor(np.array(page.render(scale=2.2).to_pil().convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    pad = 80
    canvas_img = np.full((h + 2 * pad, w + 2 * pad, 3), (120, 125, 130), np.uint8)   # table under the paper
    canvas_img[pad:pad + h, pad:pad + w] = img
    M = cv2.getRotationMatrix2D((canvas_img.shape[1] / 2, canvas_img.shape[0] / 2), 2.2, 1.0)
    rot = cv2.warpAffine(canvas_img, M, (canvas_img.shape[1], canvas_img.shape[0]), borderValue=(120, 125, 130))
    yy, xx = np.mgrid[0:rot.shape[0], 0:rot.shape[1]]
    light = 0.82 + 0.18 * (xx / rot.shape[1]) * (1 - 0.3 * yy / rot.shape[0])
    rot = np.clip(rot * light[..., None], 0, 255).astype(np.uint8)
    rot = cv2.GaussianBlur(rot, (3, 3), 0.8)
    cv2.imwrite(str(out), rot, [cv2.IMWRITE_JPEG_QUALITY, 82])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    n = bill_numbers()
    pdf = OUT / "factura_demo_2026-09.pdf"
    make_pdf(pdf, n)
    make_photo(pdf, OUT / "factura_demo_2026-09_poza.jpg")
    print(f"consumed {n['consumed']} kWh, delivered {n['delivered']} kWh (inverter {n['inverter_export']:.0f}), "
          f"total {n['total']} lei -> {pdf}")


if __name__ == "__main__":
    main()
