"""Page-number detection and page ordering."""
import os
import re
from typing import List, Optional, Tuple

from .models import PageItem

_PATTERNS = [
    re.compile(r"^\W*(?:page|pg|p)\.?\s*(\d{1,4})(?:\s*(?:of|/)\s*\d{1,4})?\W*$", re.I),
    re.compile(r"^\W*(\d{1,4})\s*(?:of|/)\s*\d{1,4}\W*$", re.I),
    re.compile(r"^\W*[-–—~•\[\(]*\s*(\d{1,4})\s*[-–—~•\]\)]*\W*$"),
]


def natural_key(path: str):
    name = os.path.basename(path).lower()
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def detect_page_number(text: str) -> Optional[int]:
    """Look at the footer, then header lines, for something that is a page number."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None
    for line in lines[-3:][::-1] + lines[:3]:
        if len(line) > 25:
            continue
        for i, pat in enumerate(_PATTERNS):
            m = pat.match(line)
            if m:
                n = int(m.group(1))
                if i == 2 and 1900 <= n <= 2100:   # a bare year, not a page
                    continue
                if n > 0:
                    return n
    return None


def order_pages(items: List[PageItem]) -> Tuple[List[PageItem], str]:
    """
    Return (ordered_items, method).
      "pages": every image had a unique page number
      "mixed": some had one; those are sorted, the rest keep their file-name slot
      "names": not enough page numbers; natural file-name order
    """
    by_name = sorted(items, key=lambda it: natural_key(it.path))
    nums = [it.page_no for it in by_name if it.page_no is not None]
    if len(nums) < 2 or len(nums) != len(set(nums)):
        return by_name, "names"
    slots = [i for i, it in enumerate(by_name) if it.page_no is not None]
    detected = sorted((by_name[i] for i in slots), key=lambda it: it.page_no)
    result = list(by_name)
    for slot, it in zip(slots, detected):
        result[slot] = it
    return result, ("pages" if len(nums) == len(items) else "mixed")
