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


# In CI set REQUIRE_OCR=1 so a missing Tesseract fails the run instead of skipping.
if os.environ.get("REQUIRE_OCR"):
    def test_tesseract_is_available_in_ci():
        assert ocr.engine_available(), "Tesseract not found on PATH"

@pytest.mark.skipif(not ocr.engine_available(), reason="Tesseract not installed")
def test_searchable_pdf_and_ocr():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.png"); _img(p, "Page 4")
        text, no = ocr.read_page(Image.open(p))
        assert "Hello" in text
        assert no == 4                      # "Page 4" in the footer is detected
        out = os.path.join(d, "o.pdf")
        build_pdf([PageItem(p)], out, searchable=True)
        assert "Hello" in PdfReader(out).pages[0].extract_text()


# ---------------------------------------------------------------- page numbers
@pytest.mark.parametrize("line", ["$250", "10%", "#5", "€45", "£12", "1800", "2101", "1999",
                                  "12/05", "10:30", "45 €", "2.5"])
def test_not_page_numbers(line):
    assert detect_page_number("some body text\n" + line) is None


@pytest.mark.parametrize("line,expected", [
    ("صفحہ 5", 5), ("صفحة ٥", 5), ("صفحہ ۵", 5), ("5 صفحہ", 5), ("صفحہ 5 از 20", 5),
    ("पृष्ठ 12", 12), ("पेज ३", 3), ("Page 5 of 20", 5), ("- 12 -", 12), ("[ 42 ]", 42),
    ("999", 999),
])
def test_page_numbers_multilingual(line, expected):
    assert detect_page_number("some body text\n" + line) == expected


# ---------------------------------------------------------------- multi-page TIFF
def _tiff(path, n):
    frames = []
    for i in range(n):
        im = Image.new("RGB", (400, 500), "white")
        ImageDraw.Draw(im).text((50, 50), f"frame {i + 1}", fill="black")
        frames.append(im)
    frames[0].save(path, save_all=True, append_images=frames[1:])


def test_multipage_tiff_frames(tmp_path):
    from core.pdfbuilder import count_frames, load_image
    p = str(tmp_path / "scan.tif"); _tiff(p, 3)
    assert count_frames(p) == 3
    assert count_frames(str(tmp_path / "x.png")) == 1
    # different frames really load different pictures
    assert load_image(p, 0, 0).tobytes() != load_image(p, 0, 2).tobytes()
    items = [PageItem(p, frame=i, frames=3) for i in range(3)]
    out = str(tmp_path / "o.pdf")
    assert build_pdf(items, out, searchable=False) == []
    assert len(PdfReader(out).pages) == 3
    assert items[1].label.endswith("[2/3]")


# ---------------------------------------------------------------- bad files / tmp file
def test_corrupt_image_is_skipped_not_fatal(tmp_path):
    good = str(tmp_path / "g.png"); _img(good, "Page 1")
    bad = str(tmp_path / "b.png"); open(bad, "wb").write(b"not an image")
    out = str(tmp_path / "o.pdf")
    skipped = build_pdf([PageItem(good), PageItem(bad), PageItem(good)], out, searchable=False)
    assert len(PdfReader(out).pages) == 2
    assert [it.path for it, _ in skipped] == [bad]


def test_all_bad_raises_and_writes_nothing(tmp_path):
    bad = str(tmp_path / "b.png"); open(bad, "wb").write(b"nope")
    out = str(tmp_path / "o.pdf")
    with pytest.raises(ValueError):
        build_pdf([PageItem(bad)], out, searchable=False)
    assert os.listdir(tmp_path) == ["b.png"]


def test_failed_save_leaves_no_tmp(tmp_path, monkeypatch):
    good = str(tmp_path / "g.png"); _img(good, "Page 1")
    out = str(tmp_path / "o.pdf")
    def boom(src, dst):
        raise PermissionError("file is open in another program")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="PDF viewer"):
        build_pdf([PageItem(good)], out, searchable=False)
    assert not any(n.endswith(".tmp") for n in os.listdir(tmp_path))


# ---------------------------------------------------------------- searchable PDF reuses OCR
@pytest.mark.skipif(not ocr.engine_available(), reason="Tesseract not installed")
def test_searchable_pdf_reuses_cached_ocr_and_stays_small(tmp_path, monkeypatch):
    from core.pdfbuilder import load_item
    p = str(tmp_path / "a.png"); _img(p, "Page 4")
    it = PageItem(p)
    it.text, it.page_no, it.text_layer = ocr.read_page_full(load_item(it), "eng")
    assert "Hello" in it.text and it.text_layer and len(it.text_layer) < 20000

    def no_ocr(*a, **k):
        raise AssertionError("OCR must not run again while building the PDF")
    monkeypatch.setattr(ocr, "read_page_full", no_ocr)
    plain, search = str(tmp_path / "p.pdf"), str(tmp_path / "s.pdf")
    build_pdf([it], plain, searchable=False)
    build_pdf([it], search, searchable=True)
    assert "Hello" in PdfReader(search).pages[0].extract_text()
    assert os.path.getsize(search) < os.path.getsize(plain) + 30_000   # text layer only
    build_pdf([it], str(tmp_path / "a4.pdf"), searchable=True, page_mode="A4 page")
    assert "Hello" in PdfReader(str(tmp_path / "a4.pdf")).pages[0].extract_text()


# ---------------------------------------------------------------- same file added twice
def test_norm_path_windows_spellings_are_equal():
    import ntpath
    from core.paths import norm_path
    spellings = ["C:/x/a.jpg", "C:/x\\a.jpg", "c:\\X\\A.JPG", "C:\\x\\sub\\..\\a.jpg", "C:/x//a.jpg"]
    assert len({norm_path(p, ntpath) for p in spellings}) == 1
    assert norm_path("C:/x/a.jpg", ntpath) != norm_path("C:/x/b.jpg", ntpath)


def test_norm_path_follows_symlinks(tmp_path):
    from core.paths import norm_path
    real = tmp_path / "a.png"; real.write_bytes(b"x")
    link = tmp_path / "link.png"
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available")
    assert norm_path(str(link)) == norm_path(str(real))


def test_page_items_have_unique_stable_ids():
    a, b = PageItem("a.jpg"), PageItem("a.jpg")
    assert a.uid != b.uid


# ---------------------------------------------------------------- rotation / TIFF / cancel
def test_rotation_swaps_page_size(tmp_path):
    p = str(tmp_path / "a.png"); _img(p, "Page 1")            # 800 x 1100 portrait
    out = str(tmp_path / "o.pdf")
    build_pdf([PageItem(p, rotation=90)], out, searchable=False)
    box = PdfReader(out).pages[0].mediabox
    assert box.width > box.height                             # rotated -> landscape


def test_rotation_applies_to_loaded_image(tmp_path):
    from core.pdfbuilder import load_image
    p = str(tmp_path / "a.png"); _img(p, "Page 1")
    assert load_image(p, 0).size == (800, 1100)
    assert load_image(p, 90).size == (1100, 800)
    assert load_image(p, 180).size == (800, 1100)


def test_tiff_single_frame_and_a4_mode(tmp_path):
    p = str(tmp_path / "scan.tif"); _tiff(p, 2)
    out = str(tmp_path / "o.pdf")
    items = [PageItem(p, frame=i, frames=2) for i in range(2)]
    assert build_pdf(items, out, searchable=False, page_mode="A4 page") == []
    assert len(PdfReader(out).pages) == 2


def test_cancel_stops_export_and_writes_nothing(tmp_path):
    import threading
    from core.pdfbuilder import Cancelled
    p = str(tmp_path / "a.png"); _img(p, "Page 1")
    ev = threading.Event(); ev.set()
    out = str(tmp_path / "o.pdf")
    with pytest.raises(Cancelled):
        build_pdf([PageItem(p), PageItem(p)], out, searchable=False, cancel=ev)
    assert not os.path.exists(out)
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []
