# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Find or build the discoal program.

discoal ships with this app as C source (vendor/discoal, GPL-3.0) with the
sweepPopn and recurrent-sweep fixes already applied. It is compiled with the
same flags used on the HPC (-O3, no -march=native) so results match across machines.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).parent / "vendor" / "discoal"
SOURCES = ["discoal_multipop.c", "discoalFunctions.c", "ranlibComplete.c", "alleleTraj.c",
           "ancestrySegment.c", "ancestrySegmentAVL.c", "ancestryVerify.c", "activeSegment.c"]
CFLAGS = ["-O3", "-I."]
EXE = "discoal.exe" if os.name == "nt" else "discoal"


def home() -> Path:
    """Per-user folder for the built program and settings."""
    base = Path(os.environ.get("DISCOAL_STUDIO_HOME", Path.home() / ".discoal-studio"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def source_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(SRC.glob("*.[ch]")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _bundled() -> Path | None:
    """A prebuilt binary shipped inside the installer (PyInstaller) or wheel."""
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(__file__).parent]
    for root in roots:
        p = root / "bin" / EXE
        if p.is_file():
            return p
    return None


def find() -> Path | None:
    env = os.environ.get("DISCOAL_STUDIO_BINARY")
    if env and Path(env).is_file():
        return Path(env)
    built = home() / "bin" / EXE
    info = home() / "bin" / "build.json"
    if built.is_file() and info.is_file() and json.loads(info.read_text()).get("source") == source_hash():
        return built
    return _bundled()


def compiler() -> str | None:
    for cc in (os.environ.get("CC"), "cc", "gcc", "clang", "x86_64-w64-mingw32-gcc"):
        if cc and shutil.which(cc):
            return cc
    return None


def build(log=print) -> Path:
    """Compile discoal from the bundled source into ~/.discoal-studio/bin."""
    cc = compiler()
    if not cc:
        hint = {"darwin": "run: xcode-select --install",
                "win32": "install MinGW-w64 gcc (e.g. winget install BrechtSanders.WinLibs.POSIX.UCRT) or use the installer"
                }.get(sys.platform, "install gcc (e.g. sudo apt install build-essential)")
        raise RuntimeError(f"No C compiler found; {hint}")
    out = home() / "bin"
    out.mkdir(exist_ok=True)
    static = ["-static"] if os.name == "nt" else []   # no MinGW runtime DLLs needed next to discoal.exe
    cmd = [cc, *CFLAGS, *static, "-o", str(out / EXE), *SOURCES, "-lm", "-fcommon"]
    log("Building discoal: " + " ".join(cmd))
    res = subprocess.run(cmd, cwd=SRC, capture_output=True, text=True)
    if res.returncode:
        raise RuntimeError("discoal build failed:\n" + res.stderr[-4000:])
    ver = subprocess.run([cc, "--version"], capture_output=True, text=True).stdout.splitlines()[:1]
    (out / "build.json").write_text(json.dumps({
        "source": source_hash(), "compiler": ver[0] if ver else cc, "flags": CFLAGS,
        "platform": platform.platform(), "binary": file_hash(out / EXE)}, indent=2))
    log("discoal is ready.")
    return out / EXE


def ensure(log=print) -> Path:
    return find() or build(log)


def describe(binary: Path) -> dict:
    info = {"path": str(binary), "sha256_16": file_hash(binary), "source_sha256_16": source_hash(),
            "patches": ["sweepPopn_fix.patch (guards sweepPopnSizes[-1] writes)",
                        "recurrentSweep_fix.patch (maps the trajectory before -R/-L sweeps)",
                        "windows_compat.patch (builds on Windows; no effect on macOS/Linux output)"]}
    meta = binary.parent / "build.json"
    if meta.is_file():
        info.update({k: v for k, v in json.loads(meta.read_text()).items() if k in ("compiler", "flags", "platform")})
    return info
