# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tanvir Anjum Joarder. See NOTICE for attribution terms.
"""Start the local server and show it in a native window (or the browser)."""
from __future__ import annotations

import socket
import threading
import time
import webbrowser

import uvicorn


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def launch(port: int = 0, use_browser: bool = False) -> None:
    from .server import TOKEN, app

    port = port or _free_port()
    url = f"http://127.0.0.1:{port}/?t={TOKEN}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)

    if not use_browser:
        try:
            import webview  # pywebview: native window using the system web engine
            webview.create_window("discoal Studio", url, width=1320, height=880, min_size=(900, 600))
            webview.start()
            server.should_exit = True
            from .server import _stop_children
            _stop_children()
            return
        except Exception as e:  # noqa: BLE001 - no GUI toolkit available: use the browser
            print(f"No app window available ({e}); opening your browser instead.")
    print(f"discoal Studio is running at {url}\nPress Ctrl+C to quit.")
    webbrowser.open(url)
    try:
        thread.join()
    except KeyboardInterrupt:
        server.should_exit = True
