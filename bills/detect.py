"""What did the user upload: a PDF with a text layer, a scanned PDF, or a photo?"""
from __future__ import annotations

IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8", b"II*\x00", b"MM\x00*")


def detect_input(data: bytes, filename: str = "") -> str:
    """Returns 'pdf' or 'image'. Whether a PDF has usable text is decided after extraction."""
    if data[:5] == b"%PDF-" or filename.lower().endswith(".pdf"):
        return "pdf"
    if data[:4] in IMAGE_MAGIC or data[:3] == b"\xff\xd8\xff" or filename.lower().endswith(
            (".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff")):
        return "image"
    raise ValueError("Format necunoscut. Încărcați un PDF sau o poză (JPG/PNG).")


def has_text(text: str, min_chars: int = 80) -> bool:
    return len("".join(text.split())) >= min_chars
