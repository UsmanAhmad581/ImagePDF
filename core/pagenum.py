"""Page-number detection and page ordering."""
import os
import re
from typing import List, Optional, Tuple

from .models import PageItem

# Decoration allowed around a page number: spaces, dashes, dots, bullets, brackets, pipes...
# Deliberately NOT currency / percent / hash / plus signs, so "$250", "10%", "#5", "€45"
# are not mistaken for pages.  (\d also matches Arabic-Indic, Persian and Devanagari digits.)
_SEP = r"[\s\-–—~•·.*_|:\[\]()<>«»]*"
# "page" in English, Urdu, Arabic, Persian and Hindi (p / pg / ص / पृ are the short forms)
_KW_LATIN = r"(?:page|pg|p)"
_KW_OTHER = r"(?:صفحہ|صفحة|صفحه|ص|पृष्ठ|पेज|पृ)"
_OF = r"(?:of|/|از|من)"

_PATTERNS = [
    # "Page 5", "p. 5", "Page 5 of 20", "صفحہ 5", "पृष्ठ 5"
    re.compile(rf"^{_SEP}(?:{_KW_LATIN}|{_KW_OTHER})\.?\s*(\d{{1,4}})"
               rf"(?:\s*{_OF}\s*(\d{{1,4}}))?{_SEP}$", re.I),
    # "5 of 20", "5/20"
    re.compile(rf"^{_SEP}(\d{{1,4}})\s*{_OF}\s*(\d{{1,4}}){_SEP}$", re.I),
    # bare number: "5", "- 5 -", "(5)"; at most 3 digits (1800 / 2101 are not pages)
    re.compile(rf"^{_SEP}(\d{{1,3}}){_SEP}$"),
    # right-to-left OCR order: "5 صفحہ"
    re.compile(rf"^{_SEP}(\d{{1,4}})\s*{_KW_OTHER}{_SEP}$"),
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
                if i in (0, 1) and m.lastindex == 2 and int(m.group(2)) < n:
                    continue                       # "12/05" is a date, not page 12 of 5
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
