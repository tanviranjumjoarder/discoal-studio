# PyInstaller recipe. Run packaging/build.sh rather than this file directly.
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "src" / "discoal_studio"
VERSION = next(l.split('"')[1] for l in (PKG / "__init__.py").read_text().splitlines()
               if l.startswith("__version__"))
exe_name = "discoal" + (".exe" if sys.platform == "win32" else "")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=[(str(PKG / "bin" / exe_name), "discoal_studio/bin")],
    datas=[(str(PKG / "static"), "discoal_studio/static"),
           (str(PKG / "presets"), "discoal_studio/presets"),
           (str(PKG / "vendor"), "discoal_studio/vendor"),
           (str(ROOT / "NOTICE"), "."), (str(ROOT / "LICENSE"), ".")],
    hiddenimports=["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on", "anthropic"],
    excludes=["tkinter", "matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="discoal-studio",
          console=sys.platform.startswith("linux"))
coll = COLLECT(exe, a.binaries, a.datas, name="discoal-studio")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="discoal Studio.app", bundle_identifier="edu.fau.discoalstudio",
                 info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": VERSION})
