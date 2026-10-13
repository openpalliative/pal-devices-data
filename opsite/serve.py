import functools
import http.server
import os
import tempfile
from pathlib import Path

from .build import load_site
from .messages_ru import msg


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".js": "text/javascript", ".webmanifest": "application/manifest+json",
                      ".woff2": "font/woff2", ".svg": "image/svg+xml", ".json": "application/json",
                      ".ics": "text/calendar"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def send_error(self, code, message=None, explain=None):
        if code == 404:
            for candidate in self._404_candidates():
                if candidate.is_file():
                    body = candidate.read_bytes()
                    self.send_response(404)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
        super().send_error(code, message, explain)

    def _404_candidates(self):
        root = Path(self.directory)
        first = self.path.strip("/").split("/", 1)[0]
        return [root / first / "404.html", root / "404.html"] if first else [root / "404.html"]

    def log_message(self, fmt, *args):
        if os.environ.get("OP_SERVE_LOG"):
            super().log_message(fmt, *args)


def serve_dir(directory: Path, port: int, host: str = "127.0.0.1") -> None:
    handler = functools.partial(NoCacheHandler, directory=str(directory))
    http.server.ThreadingHTTPServer.allow_reuse_address = True
    with http.server.ThreadingHTTPServer((host, port), handler) as httpd:
        httpd.serve_forever()


def serve(root: Path, port: int | None = None) -> None:
    root = root.resolve()
    site = load_site(root)
    site_dir = root / "_site"
    if not site_dir.is_dir():
        raise SystemExit(msg("no_site"))
    port = port or int(site["port"])
    if site["base"] == "/":
        print(msg("serve", repo=site["repo"], url=f"http://localhost:{port}/"), flush=True)
        serve_dir(site_dir, port)
        return
    with tempfile.TemporaryDirectory(prefix="opsite-") as tmp:
        name = site["base"].strip("/")
        os.symlink(site_dir, Path(tmp) / name)
        print(msg("serve", repo=site["repo"], url=f"http://localhost:{port}/{name}/"), flush=True)
        serve_dir(Path(tmp), port)
