"""Packaging hook; all other settings are in pyproject.toml.

The guides live in docs/ at the top of the repository (so they read well on GitHub), outside the
edge package. This copies them into the package as edge/docs when a wheel is built, so `edge help`,
the builder's Help Center and the MCP server's read_help work in installed copies too
(edge.help.docs_dir() looks there). An editable install (pip install -e) reads docs/ in place.
"""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

DOCS = Path(__file__).resolve().parent / "docs"
PATTERNS = ("*.md", "*.png", "reference/*.md")


class build_py_with_docs(build_py):
    def run(self) -> None:
        super().run()
        if getattr(self, "editable_mode", False) or not DOCS.is_dir():
            return
        target = Path(self.build_lib) / "edge" / "docs"
        for pattern in PATTERNS:
            for src in sorted(DOCS.glob(pattern)):
                dst = target / src.relative_to(DOCS)
                self.mkpath(str(dst.parent))
                self.copy_file(str(src), str(dst))


setup(cmdclass={"build_py": build_py_with_docs})
