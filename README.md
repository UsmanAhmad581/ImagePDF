# Image → PDF  (OCR page organiser)

Turn photos / scans of document pages into one clean PDF.
The app **reads the text** on each image, **finds the page numbers**, **puts the pages
in the right order**, and exports a **searchable PDF**.

## Features
- Add images or whole folders (also drag & drop from Explorer)
- OCR with Tesseract (English + any installed language, e.g. `urd`, `ara`, `hin`)
- Auto-order by detected page number ("Page 5", "- 5 -", "5 of 20", bare number in header/footer)
  - pages without a number keep their file-name position and are flagged orange
  - falls back to natural file-name order (img2 before img10)
- Thumbnail cards: drag to reorder, ◀ ▶ move, ⟳ rotate, ✕ remove
- Preview + recognised text for every page; export all text to `.txt`
- Optional auto-fix of sideways pages
- PDF: searchable text layer, "Fit to image" or "A4 page" sizing, progress + cancel
- Light / Dark / System theme, settings remembered

## Get the installer (Windows)
**Option A – cloud build, nothing to install:**
1. Create a free GitHub repo and upload this folder.
2. Open the **Actions** tab → **Build Windows installer** → **Run workflow**.
3. Download `ImagePDF-Setup.exe` from the run's *Artifacts*. It already includes Tesseract
   (English + Urdu + Arabic + Hindi).

**Option B – build on your PC:**
1. Install Python 3.10+, [Tesseract (UB-Mannheim)](https://github.com/UB-Mannheim/tesseract/wiki),
   and [Inno Setup 6](https://jrsoftware.org/isinfo.php).
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
Use `eng+urd` for mixed-language pages.

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
core/paths.py      Tesseract discovery + settings
tests/             unit tests
```
