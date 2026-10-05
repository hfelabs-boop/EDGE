# PyInstaller recipe for a stand-alone EDGE app (EXPERIMENTAL, not yet tested on every OS).
#   pip install pyinstaller && pyinstaller install/edge.spec
# Output: dist/EDGE/ (run EDGE or EDGE.exe inside it). Hardware SDKs (Tobii, g.tec) are not bundled.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = collect_data_files("edge", includes=["builder/static/*", "tutorials/*.yaml", "assets/*"])
datas += [(os.path.join(root, "docs"), "edge/docs")]

a = Analysis([os.path.join(root, "edge", "__main__.py")], pathex=[root], datas=datas,
             hiddenimports=collect_submodules("edge"))
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="EDGE", console=False,
          icon=os.path.join(root, "edge", "assets", "edge.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="EDGE")
