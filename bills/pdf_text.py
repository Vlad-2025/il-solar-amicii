"""Text PDFs: pdfplumber gives the words with their positions; rows are rebuilt line by line."""
from __future__ import annotations

import io

import pdfplumber


def extract_text(data: bytes, max_pages: int = 6) -> str:
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:max_pages]:
            # layout-aware text keeps a table row (label ... qty ... amount) on one line
            txt = page.extract_text(x_tolerance=1.5, y_tolerance=3, layout=False) or ""
            out.append(txt)
    return "\n".join(out)
