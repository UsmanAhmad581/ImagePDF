from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PageItem:
    """One input image / one output PDF page."""
    path: str
    rotation: int = 0              # clockwise degrees (0/90/180/270)
    text: Optional[str] = None     # OCR text (None = not read yet)
    page_no: Optional[int] = None  # page number detected in the text
    _thumb: object = field(default=None, repr=False, compare=False)

    def reset_ocr(self):
        self.text = None
        self.page_no = None
