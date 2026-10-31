"""Invisible OCR text layers for PDF pages.

Tesseract can write a PDF whose page = picture + invisible text.  We only want the
invisible text: the picture is dropped so the layer is a few KB, can be cached after the
first OCR pass, and is later laid over a (JPEG-compressed) copy of the original photo.
"""
import io
import re
from typing import Optional, Tuple

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import DecodedStreamObject, NameObject

# (x, y, width, height) in PDF points, origin bottom-left
Region = Tuple[float, float, float, float]

_IMAGE_DO = re.compile(rb"/[A-Za-z0-9_.+-]+\s+Do\b")


def strip_image(pdf_bytes: bytes) -> bytes:
    """Return a copy of Tesseract's one-page PDF with the page image removed."""
    page = PdfReader(io.BytesIO(pdf_bytes)).pages[0]
    res = page.get("/Resources")
    if res is not None:
        res = res.get_object()
        if "/XObject" in res:
            del res["/XObject"]
    data = _IMAGE_DO.sub(b"", page.get_contents().get_data())
    stream = DecodedStreamObject()
    stream.set_data(data)
    page[NameObject("/Contents")] = stream
    writer = PdfWriter()
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def overlay(page: PageObject, layer_bytes: bytes, region: Optional[Region] = None) -> None:
    """Lay the invisible text of `layer_bytes` over `page`, stretched to `region`
    (default: the whole page).  Modifies `page` in place."""
    layer = PdfReader(io.BytesIO(layer_bytes)).pages[0]
    tw, th = float(layer.mediabox.width), float(layer.mediabox.height)
    if tw <= 0 or th <= 0:
        return
    if region is None:
        region = (0.0, 0.0, float(page.mediabox.width), float(page.mediabox.height))
    rx, ry, rw, rh = region
    tr = Transformation().scale(rw / tw, rh / th).translate(rx, ry)
    page.merge_transformed_page(layer, tr)
