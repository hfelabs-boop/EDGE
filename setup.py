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
    def _write_build_info(self) -> None:
        """edge/_build.json: the commit and its date, so an installed copy built from a clone (or a git
        download) can say which build it is (`edge --version`, About EDGE). Skipped when git is not there."""
        import json
        import subprocess
        top = Path(__file__).resolve().parent
        try:
            out = subprocess.run(["git", "-C", str(top), "log", "-1", "--format=%H %cs"], capture_output=True,
                                 text=True, timeout=10)
            commit, _, date = out.stdout.strip().partition(" ")
            if out.returncode != 0 or len(commit) != 40:
                return
        except (OSError, subprocess.SubprocessError):
            return
        target = Path(self.build_lib) / "edge"
        self.mkpath(str(target))
        (target / "_build.json").write_text(json.dumps({"commit": commit, "date": date}), encoding="utf-8")

    def run(self) -> None:
        super().run()
        self._write_build_info()
        if getattr(self, "editable_mode", False) or not DOCS.is_dir():
            return
        target = Path(self.build_lib) / "edge" / "docs"
        for pattern in PATTERNS:
            for src in sorted(DOCS.glob(pattern)):
                dst = target / src.relative_to(DOCS)
                self.mkpath(str(dst.parent))
                self.copy_file(str(src), str(dst))


setup(cmdclass={"build_py": build_py_with_docs})
