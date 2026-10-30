"""Image to PDF  -  OCR page reader and organiser."""
import sys


def _enable_hidpi():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


if __name__ == "__main__":
    _enable_hidpi()
    from ui.app import App
    App().mainloop()
