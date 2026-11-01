# Image → PDF  (OCR page organiser)

Turn photos / scans of document pages into one clean PDF.
The app **reads the text** on each image, **finds the page numbers**, **puts the pages
in the right order**, and exports a **searchable PDF**.

<img width="1607" height="781" alt="Screenshot 2026-10-31 105232" src="https://github.com/user-attachments/assets/448fa175-1a7b-4635-92b8-7b37c538bd18" />

## Features
- Add images or whole folders (also drag & drop from Explorer); PNG, JPG, TIFF, BMP, WebP
  - multi-page TIFFs (scanner output) become one card per page
  - files that are skipped (unsupported type such as HEIC/GIF/PDF, duplicates) are listed, never dropped silently
- OCR with Tesseract (English + any installed language, e.g. `urd`, `ara`, `hin`)
- Auto-order by detected page number ("Page 5", "صفحہ 5", "पृष्ठ 5", "- 5 -", "5 of 20", bare 1–3 digit number in header/footer; prices, percentages and years are ignored)
  - pages without a number keep their file-name position and are flagged orange
  - falls back to natural file-name order (img2 before img10)
- Thumbnail cards: drag to reorder, ◀ ▶ move, ⟳ rotate, ✕ remove
  - **Undo (Ctrl+Z)** restores the previous page order / removed pages (up to 30 steps); Auto-order
    asks before replacing a hand-made order with a file-name order
  - pages are locked while OCR or PDF export is running (Cancel first), so a page can't change mid-job
- Preview + recognised text for every page; export all text to `.txt`
- Optional auto-fix of sideways pages
- PDF: searchable text layer, "Fit to image" or "A4 page" sizing, progress + cancel
  - the text layer comes from the "Read text" pass (no second OCR), so a searchable PDF is about
    the same size as a plain one; if you skip "Read text", pages are read once while exporting
  - an unreadable image is skipped and reported instead of aborting the whole export
- Edits made in the "Recognised text" box are kept and used by "Export text" (the PDF's hidden
  search layer is the original OCR)
- Light / Dark / System theme, settings remembered

  <img width="1917" height="1018" alt="Screenshot 2026-11-01 191438" src="https://github.com/user-attachments/assets/19cf8f33-aa6f-46f9-86a4-0d94f44d0137" />


## Get the installer (Windows)
**Option A – cloud build, nothing to install:**
1. Create a free GitHub repo and upload this folder.
2. Open the **Actions** tab → **Build Windows installer** → **Run workflow**.
3. Download `ImagePDF-Setup.exe` from the run's *Artifacts*. It already includes Tesseract
   (English + Urdu + Arabic + Hindi).

**Option B – build on your PC:**
1. Install Python 3.10+, [Tesseract (UB-Mannheim)](https://github.com/UB-Mannheim/tesseract/wiki),
   and [Inno Setup 6.3 or later](https://jrsoftware.org/isinfo.php).
2. Double-click `build_windows.bat`.
3. Installer appears in `installer_output\ImagePDF-Setup.exe`.

## Run from source (any OS)
```
pip install -r requirements.txt
# install Tesseract: Windows installer / brew install tesseract / apt install tesseract-ocr
python main.py
```

## More OCR languages
Download `<lang>.traineddata` from https://github.com/tesseract-ocr/tessdata_fast and put it in
`<install folder>\tesseract\tessdata\`. Restart the app; it appears in the language box.
Use `eng+urd` for mixed-language pages: type it in the language box and press Enter. Names that
are not installed are rejected, and changing the language clears the text read so far.

## Tests
```
pip install pytest
python -m pytest tests
```

## Project layout
```
main.py            entry point
ui/app.py          window (customtkinter)
core/pagenum.py    page-number detection + ordering
core/ocr.py        Tesseract helpers
core/pdfbuilder.py PDF creation
core/textlayer.py  invisible OCR text layer for PDF pages
core/paths.py      Tesseract discovery + settings
tests/             unit tests (test_ui.py needs a display; skipped without one)
```
