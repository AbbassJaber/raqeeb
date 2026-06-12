#!/usr/bin/env python
"""Serve the web/ cinematic demo over http (avoids file:// fetch restrictions).

    ./.venv/Scripts/python.exe scripts/serve_demo.py        # http://localhost:8000

If the default port is busy it automatically tries the next few ports.
Override the starting port with RAQEEB_DEMO_PORT.
"""
import functools
import http.server
import os
import socketserver
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PORT = int(os.getenv("RAQEEB_DEMO_PORT", "8000"))


class _Server(socketserver.TCPServer):
    allow_reuse_address = True  # reclaim a socket lingering in TIME_WAIT


def main():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB))
    for port in range(PORT, PORT + 10):
        try:
            with _Server(("", port), handler) as httpd:
                print(f"Raqeeb cinematic demo -> http://localhost:{port}   (Ctrl+C to stop)", flush=True)
                httpd.serve_forever()
            return
        except OSError as exc:
            if exc.errno in (48, 98, 10048):  # address already in use (mac/linux/win)
                print(f"port {port} is busy, trying {port + 1} ...")
                continue
            raise
    raise SystemExit(f"No free port found in {PORT}..{PORT + 9}.")


if __name__ == "__main__":
    main()
