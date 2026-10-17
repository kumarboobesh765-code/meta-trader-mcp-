"""Read-only HTTP server exposing the FTTest dashboard to the internet.

Serves exactly two files from C:\\FTTest\\logs (whitelisted, no listing):
    /ft<token>/   -> dashboard.html   (the one-pager, polls live.json)
    /ft<token>/live.json -> live.json (30s-fresh runner snapshot)

The token prefix keeps port scanners and crawlers out; without it -> 404.
Runs forever; install as scheduled task FTDashboardWeb (/ru SYSTEM, /sc onstart).

Usage: python dashboard_server.py [port]
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = r"C:\FTTest\logs"
DASH = os.path.join(LOG, "dashboard.html")
LIVE = os.path.join(LOG, "live.json")
TAPE = os.path.join(LOG, "feed.jsonl")
TOKEN = "ft26122844"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        prefix = "/" + TOKEN
        if path == prefix:
            body, ctype = self._read(DASH, "text/html; charset=utf-8")
        elif path == prefix + "/live.json":
            body, ctype = self._read(LIVE, "application/json")
        elif path == prefix + "/feed.jsonl":
            body, ctype = self._read(TAPE, "application/json")
        else:
            body, ctype = b"not found", "text/plain"
        self.send_response(200 if body != b"not found" else 404)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read(self, path, ctype):
        try:
            with open(path, "rb") as f:
                return f.read(), ctype
        except OSError:
            return b"not found", "text/plain"

    def log_message(self, fmt, *args):
        pass  # keep quiet


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("dashboard server on 0.0.0.0:%d (/%s/)" % (PORT, TOKEN), flush=True)
    srv.serve_forever()
