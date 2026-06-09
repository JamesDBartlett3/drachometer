#!/usr/bin/env python3
"""Minimal HTTP server that serves report.html, token_usage.db, and SSE live-refresh."""

import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path

PORT = 9873
SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = Path.home() / ".claude" / "token_usage.db"

# Tracks the last-known mtime of the DB file; SSE clients poll this.
_db_mtime = 0.0
_db_mtime_lock = threading.Lock()


def _watch_db():
    """Background thread: update _db_mtime when the DB file changes."""
    global _db_mtime
    while True:
        try:
            mt = DB_PATH.stat().st_mtime if DB_PATH.exists() else 0.0
            with _db_mtime_lock:
                _db_mtime = mt
        except OSError:
            pass
        time.sleep(1)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/token_usage.db":
            if DB_PATH.exists():
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                data = DB_PATH.read_bytes()
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404, "Database not found")
            return

        if path == "/events":
            self._handle_sse()
            return

        super().do_GET()

    def _handle_sse(self):
        """Server-Sent Events endpoint. Sends a 'refresh' event when DB mtime changes."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_sent = 0.0
        try:
            while True:
                with _db_mtime_lock:
                    current = _db_mtime
                if current > last_sent:
                    last_sent = current
                    self.wfile.write(f"data: {current}\n\n".encode())
                    self.wfile.flush()
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, format, *args):
        pass


def main():
    watcher = threading.Thread(target=_watch_db, daemon=True)
    watcher.start()

    class ThreadingServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    try:
        server = ThreadingServer(("127.0.0.1", PORT), Handler)
    except OSError:
        sys.exit(0)
    print(f"Serving report at http://localhost:{PORT}/report.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
