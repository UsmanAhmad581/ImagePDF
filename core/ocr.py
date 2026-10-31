"""OCR helpers built on Tesseract."""
import os
import subprocess
import tempfile
from typing import List, Optional, Tuple

import pytesseract
from PIL import Image, ImageOps

from . import textlayer
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


def read_page_full(img: Image.Image, lang: str = "eng") -> Tuple[str, Optional[int], Optional[bytes]]:
    """OCR one image once -> (text, detected_page_number, invisible_text_layer).

    A single Tesseract run writes both the plain text and a PDF text layer, so the PDF
    export can reuse the layer instead of running OCR again.  The layer is None if
    Tesseract could not produce one (the text is still returned).
    """
    gray = _prepare(img)
    with tempfile.TemporaryDirectory() as d:
        src, base = os.path.join(d, "in.png"), os.path.join(d, "out")
        gray.save(src)
        kw = {}
        if os.name == "nt":                       # no flashing console window
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            [pytesseract.pytesseract.tesseract_cmd, src, base, "-l", lang, "--dpi", "300",
             "txt", "pdf"], capture_output=True, **kw)
        if not os.path.exists(base + ".txt"):
            msg = proc.stderr.decode("utf-8", "replace").strip() or "Tesseract failed"
            raise RuntimeError(msg)
        with open(base + ".txt", encoding="utf-8") as f:
            text = f.read().replace("\f", "").strip()
        layer = None
        if os.path.exists(base + ".pdf"):
            try:
                with open(base + ".pdf", "rb") as f:
                    layer = textlayer.strip_image(f.read())
            except Exception:
                layer = None
    return text, detect_page_number(text), layer
