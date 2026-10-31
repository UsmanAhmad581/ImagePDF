import itertools
import os
from dataclasses import dataclass, field
from typing import Optional

_uids = itertools.count(1)


@dataclass
class PageItem:
    """One input image (or one frame of a multi-page TIFF) / one output PDF page."""
    path: str
    rotation: int = 0              # clockwise degrees (0/90/180/270)
    text: Optional[str] = None     # OCR text (None = not read yet)
    page_no: Optional[int] = None  # page number detected in the text
    edited: bool = False           # text was corrected by the user (not raw OCR)
    frame: int = 0                 # frame index inside a multi-page TIFF
    frames: int = 1                # total frames in the file
    error: Optional[str] = None    # why the image could not be read, if it couldn't
    _thumb: object = field(default=None, repr=False, compare=False)
    # stable identity for the UI (never reused, unlike id()); lets the grid keep one card
    # widget per page instead of rebuilding every card on each click
    uid: int = field(default_factory=lambda: next(_uids), repr=False, compare=False)
    # invisible OCR text layer (small PDF page) cached from the OCR pass, so building the
    # PDF does not have to run OCR a second time
    text_layer: Optional[bytes] = field(default=None, repr=False, compare=False)

    @property
    def label(self) -> str:
        base = os.path.basename(self.path)
        return f"{base} [{self.frame + 1}/{self.frames}]" if self.frames > 1 else base

    def reset_ocr(self):
        self.text = None
        self.page_no = None
        self.edited = False
        self.error = None
        self.text_layer = None
