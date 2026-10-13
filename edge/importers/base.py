"""Shared machinery for importers: the result object, id sanitizing, value helpers, report writing."""

from __future__ import annotations

import codecs
import re
import shutil
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


class ImportError_(ValueError):
    """An import that cannot go ahead; the message says why and what to do, in the researcher's words."""


@dataclass
class ImportResult:
    doc: dict[str, Any]
    source: Path
    platform: str
    notes: list[dict[str, str]] = field(default_factory=list)
    assets: set[str] = field(default_factory=set)          # files (relative to source dir) to copy along
    generated_files: dict[str, str | bytes] = field(default_factory=dict)  # relative path -> content to write
    stats: dict[str, int] = field(default_factory=dict)

    def note(self, level: str, where: str, message: str) -> None:
        """level: error (the result won't run until this is fixed) | unsupported (not converted) |
        approx (converted approximately) | info (converted, FYI)."""
        self.notes.append({"level": level, "where": where, "message": message})

    def count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def report_markdown(self, out_path: Path | None = None) -> str:
        lines = [f"# Import report: {self.source.name} ({self.platform})", ""]
        if self.stats:
            lines.append("Converted: " + ", ".join(f"{v} {k}" for k, v in sorted(self.stats.items())))
            lines.append("")
        groups = {"error": "Won't run until fixed", "unsupported": "Not converted (needs manual work)",
                  "approx": "Converted approximately (please check)", "info": "Notes"}
        for level, title in groups.items():
            items = [n for n in self.notes if n["level"] == level]
            if items:
                lines += [f"## {title}", ""] + [f"- **{n['where']}**: {n['message']}" for n in items] + [""]
        if not self.notes:
            lines.append("Everything was converted without remarks.")
        lines += ["", "Always dry-run the result (`edge run <file> --dry-run --report`) and compare timing "
                  "and trial counts with the original before collecting data."]
        return "\n".join(lines) + "\n"


class Ids:
    """Produces unique, valid identifiers from arbitrary names."""

    def __init__(self) -> None:
        self.taken: set[str] = set()

    def make(self, name: str, fallback: str = "item") -> str:
        base = re.sub(r"\W+", "_", str(name)).strip("_") or fallback
        if base[0].isdigit():
            base = f"{fallback}_{base}"
        cand, i = base, 2
        while cand in self.taken:
            cand = f"{base}_{i}"
            i += 1
        self.taken.add(cand)
        return cand


def ident(name: str) -> str:
    base = re.sub(r"\W+", "_", str(name)).strip("_") or "x"
    return f"v_{base}" if base[0].isdigit() else base


def num(v: Any) -> Any:
    try:
        f = float(str(v).strip())
        return int(f) if f.is_integer() and "." not in str(v) else f
    except (TypeError, ValueError):
        return v


def ms(v: Any) -> Any:
    """Milliseconds (number or string) -> seconds; non-numeric passes through."""
    n = num(v)
    return round(n / 1000.0, 6) if isinstance(n, (int, float)) else n


KEY_NAMES = {
    "space": "space", "spacebar": "space", "enter": "return", "return": "return", "leftarrow": "left",
    "rightarrow": "right", "uparrow": "up", "downarrow": "down", "left": "left", "right": "right", "up": "up",
    "down": "down", "escape": "escape", "esc": "escape", "tab": "tab", "backspace": "backspace",
    "arrowleft": "left", "arrowright": "right", "arrowup": "up", "arrowdown": "down", " ": "space",
}


def key_name(k: str) -> str:
    k = str(k).strip()
    low = k.lower().strip("{}")
    return KEY_NAMES.get(low, low if len(low) > 1 else k.lower())


def decode_text(data: bytes) -> str:
    """Text of a file in whatever encoding it was saved: UTF-8 (with or without a BOM), UTF-16 ("Unicode" in
    Windows programs such as E-Studio, with or without a BOM) or a Windows code page. Line ends become \\n."""
    text = None
    for bom, enc in ((codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"), (codecs.BOM_UTF8, "utf-8-sig"),
                     (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            text = data.decode(enc, errors="replace")
            break
    if text is None:
        head = data[:2000]
        if len(head) >= 4 and head.count(0) > len(head) // 4:   # UTF-16 without a BOM: every other byte is 0
            le = head[1::2].count(0) > head[0::2].count(0)
            text = data.decode("utf-16-le" if le else "utf-16-be", errors="replace")
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("cp1252", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text(path: Path) -> str:
    return decode_text(Path(path).read_bytes())


def portable_path(p: Any) -> Any:
    """A file name written on Windows (``stimuli\\red.png``) as the relative path that works on every computer."""
    if isinstance(p, str) and "\\" in p and not p.startswith("$"):
        return p.replace("\\", "/")
    return p


# ------------------------------------------------------------------ simple HTML -> text component
_HTML = re.compile(r"<\s*/?\s*(?:br|b|i|u|s|em|strong|span|font|p|div|h[1-6]|center|small|big|sup|sub|strike|li|ul|ol|"
                   r"label|pre|code|tt)\b[^>]*>|&(?:#\d+|#x[0-9a-f]+|[a-z]+);", re.I)
_BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "center", "pre", "table", "tr"}
_VOID = {"br", "img", "hr", "input", "meta", "link", "wbr", "source", "col", "area"}
_TAG_DROPPED = {"u": "underline", "s": "strike-through", "strike": "strike-through", "sup": "superscript",
                "sub": "subscript", "small": "smaller text", "big": "bigger text"}
_CSS_IGNORED = {"text-align", "line-height", "display", "width", "max-width", "min-width", "height", "max-height",
                "min-height", "box-sizing", "white-space"}
_STYLE_LABEL = {"color": "colour", "height": "font size", "bold": "bold", "italic": "italic"}


def has_html(s: Any) -> bool:
    return isinstance(s, str) and bool(_HTML.search(s))


def css_px(v: str) -> float | None:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(px|pt)?\s*", str(v), re.I)
    if not m:
        return None
    n = float(m.group(1))
    return round(n * 4 / 3, 2) if (m.group(2) or "").lower() == "pt" else n


def css_color(v: str) -> str | None:
    """A CSS/HTML colour as EDGE writes it (#rrggbb or a colour name EDGE knows), or None."""
    from ..backends.base import NAMED_COLORS
    s = str(v).strip().lower().replace("!important", "").strip()
    if re.fullmatch(r"#[0-9a-f]{3}|#[0-9a-f]{6}", s):
        return s
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)", s)
    if m:
        return "#%02x%02x%02x" % tuple(min(255, int(x)) for x in m.groups())
    return s if s in NAMED_COLORS else None


class _HTMLText(HTMLParser):
    def __init__(self, collapse: bool):
        super().__init__(convert_charrefs=True)
        self.collapse = collapse
        self.out: list[str] = []
        self.stack: list[tuple[str, dict[str, Any]]] = []
        self.runs: list[dict[str, Any]] = []        # the styling in effect for each piece of visible text
        self.dropped: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self.out.append("\n")
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        st: dict[str, Any] = {}
        if tag in ("b", "strong") or re.fullmatch(r"h[1-6]", tag):
            st["bold"] = True
        if tag in ("i", "em"):
            st["italic"] = True
        if tag in _TAG_DROPPED:
            self.dropped.add(_TAG_DROPPED[tag])
        if a.get("color"):                           # <font color=..>, OpenSesame's <span color=..>
            st["color"] = css_color(a["color"]) or a["color"]
        if a.get("size"):                            # OpenSesame's <span size=..> is in pixels
            px = css_px(a["size"]) if tag == "span" else None
            if px:
                st["height"] = px
            else:
                self.dropped.add("font size")
        for decl in (a.get("style") or "").split(";"):
            k, _, v = decl.partition(":")
            k, v = k.strip().lower(), v.strip()
            if not k:
                continue
            if k == "color":
                st["color"] = css_color(v) or v
            elif k == "font-size":
                px = css_px(v)
                if px:
                    st["height"] = px
                else:
                    self.dropped.add(f"font-size {v}")
            elif k == "font-weight":
                st["bold"] = v.lower() in ("bold", "bolder") or (v.isdigit() and int(v) >= 600)
            elif k == "font-style":
                st["italic"] = v.lower() in ("italic", "oblique")
            elif k not in _CSS_IGNORED and not k.startswith(("margin", "padding")):
                self.dropped.add(k)
        if tag in _BLOCK and self.out and not "".join(self.out).endswith("\n"):
            self.out.append("\n")
        if tag not in _VOID:
            self.stack.append((tag, st))

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in _BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if any(t in ("script", "style") for t, _ in self.stack):    # code, not text on the screen
            return
        if self.collapse and not any(t == "pre" for t, _ in self.stack):
            data = re.sub(r"[ \t\n\r\f]+", " ", data)        # as a browser does (&nbsp; stays)
        self.out.append(data)
        if data.strip():
            eff: dict[str, Any] = {}
            for _, st in self.stack:
                eff.update(st)
            self.runs.append(eff)


def html_to_text(h: str, collapse: bool = True) -> tuple[str, dict[str, Any], list[str]]:
    """What a text component should show for simple HTML: the text (``<br>`` and paragraphs become line breaks,
    ``&amp;`` becomes ``&``), the styling a text component can carry (color, height in px, bold, italic) when it
    applies to all of the text, and a list of the styling that could not be kept. ``collapse``: runs of spaces and
    line breaks in the source count as one space, as in a browser."""
    if not has_html(h):
        return h, {}, []
    p = _HTMLText(collapse)
    p.feed(h)
    p.close()
    text = "\n".join(line.strip() for line in "".join(p.out).splitlines()).strip()
    style: dict[str, Any] = {}
    for prop, label in _STYLE_LABEL.items():
        vals = [r.get(prop) or None for r in p.runs]
        if len({repr(v) for v in vals}) > 1:
            p.dropped.add(f"{label} on part of the text")
        elif vals and vals[0] not in (None, False):
            style[prop] = vals[0]
    if "color" in style:
        c = css_color(style["color"])
        if c is None:
            p.dropped.add(f"colour '{style['color']}' (write it as #rrggbb)")
            del style["color"]
        else:
            style["color"] = c
    return text, style, sorted(p.dropped)


def inside(out_dir: Path, rel: str) -> Path | None:
    """``out_dir / rel`` when that stays inside ``out_dir`` (imported files name their own paths)."""
    if not rel or Path(rel).is_absolute() or (len(rel) > 1 and rel[1] == ":"):
        return None
    dest = (out_dir / rel).resolve()
    root = out_dir.resolve()
    return dest if root in dest.parents else None


def finalize(result: ImportResult, out_dir: Path) -> list[str]:
    """Copy referenced assets next to the converted experiment; returns files that were missing."""
    missing = []
    src_dir = result.source.parent
    for rel in sorted(result.assets):
        src = (src_dir / rel)
        dest = inside(out_dir, rel)
        if dest is None:
            result.note("approx", "files", f"skipped '{rel}': it would land outside the experiment folder")
            continue
        if not src.is_file():
            missing.append(rel)
            continue
        if dest.resolve() == src.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    for rel, text in result.generated_files.items():
        dest = inside(out_dir, rel)
        if dest is None:
            result.note("approx", "files", f"skipped '{rel}': it would land outside the experiment folder")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            dest.write_bytes(text)
        else:
            dest.write_text(text, encoding="utf-8")
    for m in missing:
        result.note("approx", "files", f"referenced file '{m}' was not found next to the source; copy it manually")
    return missing
