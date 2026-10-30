"""OCR helpers built on Tesseract."""
from typing import List, Optional, Tuple

import pytesseract
from PIL import Image, ImageOps

from .pagenum import detect_page_number

MAX_OCR_SIDE = 3500


def engine_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def languages() -> List[str]:
    try:
        langs = [l for l in pytesseract.get_languages(config="") if l != "osd"]
        return sorted(langs) or ["eng"]
    except Exception:
        return ["eng"]


def _prepare(img: Image.Image) -> Image.Image:
    g = ImageOps.autocontrast(img.convert("L"))
    if max(g.size) > MAX_OCR_SIDE:
        g.thumbnail((MAX_OCR_SIDE, MAX_OCR_SIDE))
    return g


def detect_rotation(img: Image.Image) -> int:
    """Clockwise degrees needed to make the page upright (0 if unsure/unavailable)."""
    try:
        osd = pytesseract.image_to_osd(_prepare(img))
        rot, conf = 0, 0.0
        for line in osd.splitlines():
            if line.startswith("Rotate:"):
                rot = int(line.split(":")[1])
            elif line.startswith("Orientation confidence:"):
                conf = float(line.split(":")[1])
        return rot if conf >= 2.0 else 0
    except Exception:
        return 0


def read_page(img: Image.Image, lang: str = "eng") -> Tuple[str, Optional[int]]:
    """OCR one image -> (text, detected_page_number)."""
    text = pytesseract.image_to_string(_prepare(img), lang=lang)
    return text, detect_page_number(text)
