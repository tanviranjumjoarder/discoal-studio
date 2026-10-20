# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Entry point for the packaged app (PyInstaller)."""
import multiprocessing
import os
import sys

from discoal_studio.cli import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    # A windowed app (Windows .exe, macOS .app) may start without stdout/stderr;
    # uvicorn's logging calls sys.stdout.isatty(), so give it somewhere to write.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))
    app()
