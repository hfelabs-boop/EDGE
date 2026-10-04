"""Shows one HTML page in a native window (pywebview), used by the ``html`` component.

Runs as its own process so the experiment's OpenGL window and the web view never fight over
the main thread. ``python -m edge.htmlview URL [fullscreen]``.
"""

from __future__ import annotations

import sys


def main() -> None:
    import webview  # pywebview

    url = sys.argv[1]
    fullscreen = len(sys.argv) < 3 or sys.argv[2] == "1"
    win = webview.create_window("EDGE", url, fullscreen=fullscreen)
    webview.start()
    del win


if __name__ == "__main__":
    main()
