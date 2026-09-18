"""Loopback-only local UI. No public account service or arbitrary file serving."""
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import threading
from urllib.parse import urlparse

from .cli import route, state
from .config import save_config
from .store import export_csv


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, store, lock, **kwargs):
        self.store, self.lock = store, lock
        super().__init__(*args, **kwargs)

    def log_message(self, *args):
        pass  # Don't log user configuration or URLs.

    def send(self, code, content, content_type="application/json"):
        data = json.dumps(content, allow_nan=False).encode() if content_type == "application/json" else content.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if self.path == "/api/export.csv":
            self.send_header("Content-Disposition", 'attachment; filename="apartments.csv"')
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in {f"http://{host}" for host in allowed}

    def do_GET(self):
        if not self.local_request():
            self.send(403, {"error": "Local requests only"})
            return
        try:
            path = urlparse(self.path).path
            if path == "/api/state":
                self.send(200, state(self.store))
            elif path == "/api/export.csv":
                self.send(200, export_csv(self.store.listings()), "text/csv")
            else:
                assets = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
                          "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}
                if path not in assets:
                    self.send(404, {"error": "Not found"})
                    return
                filename, mime = assets[path]
                self.send(200, files("housing").joinpath("web", filename).read_text(), mime)
        except (ValueError, OSError, RuntimeError) as exc:
            self.send(400, {"error": str(exc)})

    def do_POST(self):
        if not self.local_request():
            self.send(403, {"error": "Local requests only"})
            return
        if self.headers.get_content_type() != "application/json":
            self.send(415, {"error": "Send application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 10 * 1024 * 1024:
                raise ValueError("JSON body must be 1 byte to 10 MB")
            body = json.loads(self.rfile.read(length))
            if not self.lock.acquire(blocking=False):
                self.send(409, {"error": "Another write or route calculation is running"})
                return
            try:
                if self.path == "/api/config":
                    save_config(self.store.workspace, body)
                    self.send(200, {"saved": True})
                elif self.path == "/api/import":
                    if not isinstance(body, dict) or not isinstance(body.get("listings"), list):
                        raise ValueError("Expected {listings: [...]}")
                    self.send(200, self.store.import_rows(body["listings"]))
                elif self.path == "/api/routes":
                    self.send(200, route(self.store))
                elif self.path == "/api/geocode":
                    from .geocode import geocode_address
                    if not isinstance(body, dict):
                        raise ValueError("Expected an address object")
                    self.send(200, geocode_address(body.get("address"), self.store.workspace / "geocodes"))
                else:
                    self.send(404, {"error": "Not found"})
            finally:
                self.lock.release()
        except (ValueError, OSError, RuntimeError) as exc:
            self.send(400, {"error": str(exc)})


def serve(store, port):
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, store=store, lock=threading.Lock()))
    print(f"Apartment Decision Lab: http://127.0.0.1:{server.server_port} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
