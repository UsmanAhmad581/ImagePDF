import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader
from core.models import PageItem
from core.pagenum import detect_page_number, order_pages
from core.pdfbuilder import build_pdf
from core import ocr


@pytest.mark.parametrize("text,expected", [
    ("Hello\nworld\nPage 7", 7), ("Intro\n- 12 -", 12), ("text\n5 of 20", 5),
    ("text\n3", 3), ("text\nCopyright 2024", None), ("only a long sentence here with no number", None),
    ("", None), ("42\nbody text\nmore", 42),
])
def test_detect(text, expected):
    assert detect_page_number(text) == expected


def mk(name, page):
    it = PageItem(path=name); it.page_no = page; return it


def test_order_all_detected():
    items = [mk("a.jpg", 3), mk("b.jpg", 1), mk("c.jpg", 2)]
    res, m = order_pages(items)
    assert m == "pages" and [i.page_no for i in res] == [1, 2, 3]


def test_order_mixed_keeps_undetected_in_place():
    items = [mk("1.jpg", 3), mk("2.jpg", None), mk("3.jpg", 1)]
    res, m = order_pages(items)
    assert m == "mixed" and [i.path for i in res] == ["3.jpg", "2.jpg", "1.jpg"]


def test_order_names_fallback_natural():
    items = [mk("img10.jpg", None), mk("img2.jpg", None)]
    res, m = order_pages(items)
    assert m == "names" and [i.path for i in res] == ["img2.jpg", "img10.jpg"]


def test_duplicates_fall_back():
    _, m = order_pages([mk("a1.jpg", 2), mk("a2.jpg", 2), mk("a3.jpg", None)])
    assert m == "names"


def _img(path, label):
    im = Image.new("RGB", (800, 1100), "white")
    d = ImageDraw.Draw(im)
    d.text((100, 100), "Hello world body text", fill="black")
    d.text((380, 1050), label, fill="black")
    im.save(path)


def test_plain_pdf():
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for i in range(3):
            p = os.path.join(d, f"{i}.png"); _img(p, f"Page {i+1}"); paths.append(p)
        out = os.path.join(d, "o.pdf")
        build_pdf([PageItem(p) for p in paths], out, searchable=False, page_mode="A4 page")
        assert len(PdfReader(out).pages) == 3


@pytest.mark.skipif(not ocr.engine_available(), reason="Tesseract not installed")
def test_searchable_pdf_and_ocr():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.png"); _img(p, "Page 4")
        text, no = ocr.read_page(Image.open(p))
        assert "Hello" in text
        out = os.path.join(d, "o.pdf")
        build_pdf([PageItem(p)], out, searchable=True)
        assert "Hello" in PdfReader(out).pages[0].extract_text()
