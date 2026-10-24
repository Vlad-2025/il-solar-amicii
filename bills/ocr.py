"""Scanned PDFs and photos: render, clean up with OpenCV, OCR with Tesseract (Romanian + English)."""
from __future__ import annotations

import io
from functools import lru_cache

import cv2
import numpy as np


@lru_cache(maxsize=1)
def languages() -> str:
    import pytesseract

    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 - tesseract missing or misconfigured
        return "eng"
    return "ron+eng" if "ron" in langs else "eng"


def tesseract_available() -> bool:
    import pytesseract

    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


def render_pdf(data: bytes, scale: float = 3.0, max_pages: int = 4) -> list[np.ndarray]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    images = []
    for i in range(min(len(pdf), max_pages)):
        pil = pdf[i].render(scale=scale).to_pil().convert("RGB")
        images.append(cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR))
    return images


def load_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:  # HEIC and friends: let Pillow try
        from PIL import Image

        pil = Image.open(io.BytesIO(data)).convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    return img


def deskew_angle(gray: np.ndarray) -> float:
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thresh > 0)).astype(np.float32)
    if len(coords) < 100:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle > 45:
        angle -= 90
    elif angle < -45:
        angle += 90
    return float(angle) if abs(angle) <= 15 else 0.0


def preprocess(img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape
    if max(h, w) < 2000:                                  # phone thumbnails: upscale for OCR
        f = 2000 / max(h, w)
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        h, w = gray.shape
    angle = deskew_angle(gray)
    if abs(angle) > 0.3:
        M = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
        gray = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)


def ocr_image(img: np.ndarray) -> tuple[str, float]:
    """Returns text (one line per OCR line) and the mean word confidence (0-100)."""
    import pytesseract

    clean = preprocess(img)
    data = pytesseract.image_to_data(clean, lang=languages(), config="--psm 6",
                                     output_type=pytesseract.Output.DICT)
    lines: dict[tuple, list[str]] = {}
    confs = []
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append(word)
        c = float(data["conf"][i])
        if c >= 0:
            confs.append(c)
    text = "\n".join(" ".join(ws) for _, ws in sorted(lines.items()))
    return text, float(np.mean(confs)) if confs else 0.0


def ocr_pdf(data: bytes) -> tuple[str, float]:
    texts, confs = [], []
    for img in render_pdf(data):
        t, c = ocr_image(img)
        texts.append(t)
        confs.append(c)
    return "\n".join(texts), float(np.mean(confs)) if confs else 0.0
