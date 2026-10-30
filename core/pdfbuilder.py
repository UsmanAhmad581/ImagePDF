"""Create the output PDF from an ordered list of PageItems."""
import io
import os
import threading
from typing import Callable, List, Optional

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

from .models import PageItem

A4_PX = (2480, 3508)     # A4 @ 300 dpi
A4_LONG_SIDE_IN = 11.69


class Cancelled(Exception):
    pass


def load_image(path: str, rotation: int = 0) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if rotation:
        img = img.rotate(-rotation, expand=True)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, "white")
        rgba = img.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return img.convert("RGB")


def fit_on_a4(img: Image.Image) -> Image.Image:
    page = Image.new("RGB", A4_PX, "white")
    if img.width > img.height * 1.2:           # landscape picture -> landscape page
        page = page.rotate(90, expand=True)
    pw, ph = page.size
    img = img.copy()
    img.thumbnail((pw - 80, ph - 80), Image.LANCZOS)
    page.paste(img, ((pw - img.width) // 2, (ph - img.height) // 2))
    return page


def build_pdf(items: List[PageItem], out_path: str, *, searchable: bool = True,
              lang: str = "eng", page_mode: str = "Fit to image",
              progress: Optional[Callable[[int, int, str], None]] = None,
              cancel: Optional[threading.Event] = None,
              title: str = "Scanned document") -> None:
    if not items:
        raise ValueError("No images to convert.")
    if searchable:
        import pytesseract

    writer = PdfWriter()
    total = len(items)
    for n, it in enumerate(items, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        img = load_image(it.path, it.rotation)
        if page_mode.startswith("A4"):
            img, dpi = fit_on_a4(img), 300
        else:
            dpi = max(72, round(max(img.size) / A4_LONG_SIDE_IN))

        if searchable:
            data = pytesseract.image_to_pdf_or_hocr(
                img, extension="pdf", lang=lang, config=f"--dpi {dpi}")
        else:
            buf = io.BytesIO()
            img.save(buf, "PDF", resolution=float(dpi), quality=90)
            data = buf.getvalue()

        for page in PdfReader(io.BytesIO(data)).pages:
            writer.add_page(page)
        if progress:
            progress(n, total, f"Building page {n} of {total}")

    writer.add_metadata({"/Title": title, "/Producer": "ImagePDF"})
    tmp = out_path + ".tmp"
    with open(tmp, "wb") as f:
        writer.write(f)
    os.replace(tmp, out_path)
