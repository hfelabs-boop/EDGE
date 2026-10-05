"""Right-to-left text (Hebrew, Arabic, Persian, Urdu …) for the experiment window.

Browsers (surveys, HTML pages, Try it) lay out right-to-left text natively. The OpenGL experiment
window does not, so text that contains right-to-left characters is converted to *visual order* here,
and Arabic-script letters are joined into their contextual forms, before it is drawn. This uses the
optional packages ``python-bidi`` and ``arabic-reshaper`` (``pip install "edge-experiments[rtl]"``).
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

_RTL_RANGES = re.compile("[֐-ࣿיִ-﷿ﹰ-ﻼ]")
_ARABIC = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-ﻼ]")
RTL_LANGUAGES = {"ar", "he", "iw", "fa", "ur", "yi", "ps", "sd", "ug", "ckb", "dv"}


def has_rtl(text: str) -> bool:
    return bool(_RTL_RANGES.search(str(text or "")))


def is_rtl_language(lang: str | None) -> bool:
    return bool(lang) and str(lang).split("-")[0].lower() in RTL_LANGUAGES


def first_strong_rtl(text: str) -> bool:
    """Direction of a paragraph by its first strong character (the Unicode rule used by 'auto')."""
    for ch in str(text or ""):
        d = unicodedata.bidirectional(ch)
        if d in ("R", "AL"):
            return True
        if d == "L":
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
    if _ARABIC.search(text):
        try:
            import arabic_reshaper
            text = arabic_reshaper.reshape(text)
        except ImportError:
            pass
    base = {"rtl": "R", "ltr": "L"}.get(direction)
    lines = []
    for line in text.split("\n"):
        lines.append(get_display(line, base_dir=base) if base else get_display(line))
    return "\n".join(lines)


def guess_language(text: str) -> str | None:
    """A language for right-to-left text by its script: Hebrew -> he, Arabic script -> ar (or fa / ur when
    letters only those languages use appear). None for anything else."""
    t = str(text or "")
    if re.search("[\u0590-\u05ff]", t):
        return "he"
    if _ARABIC.search(t):
        if re.search("[\u0679\u0688\u0691\u06ba\u06be\u06c1\u06d2]", t):
            return "ur"
        if re.search("[\u067e\u0686\u0698\u06af\u06a9\u06cc]", t):
            return "fa"
        return "ar"
    return None
