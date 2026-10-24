"""Bill parsing pipeline: detect input -> text (pdfplumber or OCR) -> supplier -> fields -> validation."""
from __future__ import annotations

from bills import detect, pdf_text, suppliers, terms_ro, validate


def parse_bill(data: bytes, filename: str = "") -> dict:
    kind = detect.detect_input(data, filename)
    warnings: list[str] = []
    ocr_conf = None
    if kind == "pdf":
        text = pdf_text.extract_text(data)
        method = "pdf_text"
        if not detect.has_text(text):
            from bills import ocr
            if not ocr.tesseract_available():
                raise RuntimeError("PDF scanat, dar Tesseract nu este instalat pe server.")
            text, ocr_conf = ocr.ocr_pdf(data)
            method = "ocr"
    else:
        from bills import ocr
        if not ocr.tesseract_available():
            raise RuntimeError("Tesseract nu este instalat pe server; încărcați factura ca PDF.")
        text, ocr_conf = ocr.ocr_image(ocr.load_image(data))
        method = "ocr"
    if ocr_conf is not None and ocr_conf < 60:
        warnings.append("Poza este greu de citit. Fotografiați factura de aproape, drept și la lumină bună.")

    plain = terms_ro.plain(text)
    supplier = suppliers.detect(plain)
    template = supplier["template"] if supplier else suppliers.generic
    fields = template.extract(text, plain)
    fields["supplier"] = supplier["name"] if supplier else None
    fields["parse_method"] = method
    fields["ocr_confidence"] = round(ocr_conf, 1) if ocr_conf is not None else None
    fields["raw_text"] = text

    checks = validate.validate(fields)
    fields["confidence"] = validate.apply_confidence(fields, checks)
    fields["validation"] = checks
    if not fields["lines"]:
        warnings.append("Nu am găsit nicio linie cunoscută pe factură. Completați valorile manual mai jos.")
    if supplier is None:
        warnings.append("Furnizor necunoscut: am folosit extragerea generică. Verificați valorile.")
    fields["warnings"] = warnings
    return fields
