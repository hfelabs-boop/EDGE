"""Right-to-left text (Hebrew, Yiddish) for the experiment window.

Browsers (surveys, HTML pages, Try it) lay out right-to-left text natively. The OpenGL experiment
window does not, so text that contains Hebrew characters is converted to *visual order* here before
it is drawn. This uses the optional package ``python-bidi`` (``pip install "edge-experiments[rtl]"``).
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_RTL_RANGES = re.compile("[\u0590-\u05ff\ufb1d-\ufb4f]")
RTL_LANGUAGES = {"he", "iw", "yi"}


def has_rtl(text: str) -> bool:
    return bool(_RTL_RANGES.search(str(text or "")))


def is_rtl_language(lang: str | None) -> bool:
    return bool(lang) and str(lang).split("-")[0].lower() in RTL_LANGUAGES


def first_strong_rtl(text: str) -> bool:
    """Direction of a paragraph by its first strong letter (Hebrew = right to left)."""
    for ch in str(text or ""):
        if _RTL_RANGES.match(ch):
            return True
        if unicodedata.bidirectional(ch) == "L":
            return False
    return False


def available() -> bool:
    try:
        import bidi.algorithm  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=4096)
def visual(text: str, direction: str = "auto") -> str:
    """Text in the order it must be drawn by a left-to-right renderer. Unchanged when not needed."""
    if not has_rtl(text):
        return text
    try:
        from bidi.algorithm import get_display
    except ImportError:
        return text
    base = {"rtl": "R", "ltr": "L"}.get(direction)
    return "\n".join(get_display(line, base_dir=base) if base else get_display(line) for line in text.split("\n"))


def guess_language(text: str) -> str | None:
    """'he' for Hebrew-script text, else None."""
    return "he" if has_rtl(text) else None
