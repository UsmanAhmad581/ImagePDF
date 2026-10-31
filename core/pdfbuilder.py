"""Create the output PDF from an ordered list of PageItems."""
import io
import os
import threading
from typing import Callable, List, Optional, Tuple

from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

from . import textlayer
from .models import PageItem

A4_PX = (2480, 3508)     # A4 @ 300 dpi
A4_LONG_SIDE_IN = 11.69
TIFF_TYPES = (".tif", ".tiff")


class Cancelled(Exception):
    pass


def count_frames(path: str) -> int:
    """Number of pages in a multi-page TIFF (1 for everything else / unreadable files)."""
    if not path.lower().endswith(TIFF_TYPES):
        return 1
    try:
        with Image.open(path) as im:
            return max(1, int(getattr(im, "n_frames", 1)))
    except Exception:
        return 1


def load_image(path: str, rotation: int = 0, frame: int = 0) -> Image.Image:
    with Image.open(path) as src:
        if frame:
            src.seek(frame)
        img = ImageOps.exif_transpose(src)
        if rotation:
            img = img.rotate(-rotation, expand=True)
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, "white")
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            return bg
        return img.convert("RGB")


def load_item(it: PageItem) -> Image.Image:
    return load_image(it.path, it.rotation, it.frame)


def a4_layout(img: Image.Image):
    """Centre `img` on a white A4 page. Returns (page_image, region) where region is the
    (x, y, w, h) the picture occupies on the page in PDF points (origin bottom-left)."""
    page = Image.new("RGB", A4_PX, "white")
    if img.width > img.height * 1.2:           # landscape picture -> landscape page
        page = page.rotate(90, expand=True)
    pw, ph = page.size
    img = img.copy()
    img.thumbnail((pw - 80, ph - 80), Image.LANCZOS)
    ox, oy = (pw - img.width) // 2, (ph - img.height) // 2
    page.paste(img, (ox, oy))
    k = 72.0 / 300.0
    return page, (ox * k, (ph - oy - img.height) * k, img.width * k, img.height * k)


def fit_on_a4(img: Image.Image) -> Image.Image:
    return a4_layout(img)[0]


def _page_label(it: PageItem) -> str:
    return it.label


def build_pdf(items: List[PageItem], out_path: str, *, searchable: bool = True,
              lang: str = "eng", page_mode: str = "Fit to image",
              progress: Optional[Callable[[int, int, str], None]] = None,
              cancel: Optional[threading.Event] = None,
              title: str = "Scanned document") -> List[Tuple[PageItem, str]]:
    """Write the PDF. Images that cannot be read are skipped, not fatal.

    Returns the list of (item, reason) that were left out. Raises ValueError if no
    page at all could be built.
    """
    if not items:
        raise ValueError("No images to convert.")

    writer = PdfWriter()
    skipped: List[Tuple[PageItem, str]] = []
    total = len(items)
    for n, it in enumerate(items, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            img = load_item(it)
        except Exception as ex:
            skipped.append((it, f"{type(ex).__name__}: {ex}"))
            if progress:
                progress(n, total, f"Skipped unreadable image {n} of {total}")
            continue

        region = None
        if page_mode.startswith("A4"):
            page_img, region = a4_layout(img)
            dpi = 300
        else:
            page_img, dpi = img, max(72, round(max(img.size) / A4_LONG_SIDE_IN))

        # picture only: JPEG-compressed, no OCR here
        buf = io.BytesIO()
        page_img.save(buf, "PDF", resolution=float(dpi), quality=90)
        page = PdfReader(io.BytesIO(buf.getvalue())).pages[0]

        if searchable:
            layer = it.text_layer
            if layer is None:                  # page was never read: do it now, once
                from . import ocr
                _, _, layer = ocr.read_page_full(img, lang)
                it.text_layer = layer
            if layer:
                textlayer.overlay(page, layer, region)
        writer.add_page(page)
        if progress:
            progress(n, total, f"Building page {n} of {total}")

    if len(writer.pages) == 0:
        raise ValueError("None of the images could be read:\n" + "\n".join(
            f"• {it.label}: {why}" for it, why in skipped[:8]))

    try:                                       # share the identical font in every page
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    except Exception:
        pass
    writer.add_metadata({"/Title": title, "/Producer": "ImagePDF"})

    tmp = out_path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            writer.write(f)
        os.replace(tmp, out_path)
    except OSError as ex:
        raise OSError(f"Could not save “{out_path}”.\n"
                      "If the file is open in a PDF viewer, close it and try again.\n\n"
                      f"({ex})") from ex
    finally:
        if os.path.exists(tmp):                # never leave name.pdf.tmp behind
            try:
                os.remove(tmp)
            except OSError:
                pass
    return skipped
