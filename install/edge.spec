# PyInstaller recipe for a stand-alone EDGE app (EXPERIMENTAL, not yet tested on every OS).
#   pip install pyinstaller && pyinstaller install/edge.spec
# Output: dist/EDGE/ (run EDGE or EDGE.exe inside it). Hardware SDKs (Tobii, g.tec) are not bundled.
# The release workflow checks the result with:  dist/EDGE/EDGE --version  and a dry run.
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, root)      # bundle this copy of EDGE, whether or not (or wherever) it is pip-installed
# the same data files as package-data in pyproject.toml, plus the guides for the Help Center
datas = collect_data_files("edge", includes=["builder/static/*", "tutorials/*.yaml", "survey_page/*", "assets/*"])
datas += [(os.path.join(root, "docs"), "edge/docs")]

# edge/__main__.py imports edge.cli absolutely, so it works as the app's entry script
a = Analysis([os.path.join(root, "edge", "__main__.py")], pathex=[root], datas=datas,
             hiddenimports=collect_submodules("edge"))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EDGE", console=False,
          icon=os.path.join(root, "edge", "assets", "edge.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="EDGE")
