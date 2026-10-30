"""Locating bundled resources and the Tesseract OCR engine."""
import json
import os
import shutil
import sys

APP_NAME = "ImagePDF"


def base_dir() -> str:
    """Folder that contains the app (works for source runs and PyInstaller)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_dir() -> str:
    root = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    path = os.path.join(root, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def configure_tesseract():
    """Point pytesseract at a bundled or installed Tesseract. Returns its path or None."""
    import pytesseract

    exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    bundled = os.path.join(base_dir(), "tesseract", exe)
    if os.path.exists(bundled):
        pytesseract.pytesseract.tesseract_cmd = bundled
        os.environ["TESSDATA_PREFIX"] = os.path.join(base_dir(), "tesseract", "tessdata")
        return bundled
    found = shutil.which("tesseract")
    if found:
        return found
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
              r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            return p
    return None


DEFAULT_SETTINGS = {
    "language": "eng",
    "searchable": True,
    "page_mode": "Fit to image",
    "appearance": "System",
    "auto_rotate": False,
    "last_dir": "",
}


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    try:
        with open(os.path.join(config_dir(), "settings.json"), encoding="utf-8") as f:
            data.update(json.load(f))
    except Exception:
        pass
    return data


def save_settings(data: dict) -> None:
    try:
        with open(os.path.join(config_dir(), "settings.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
