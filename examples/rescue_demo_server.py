"""Serve only the comparison page and its selected local inputs over loopback."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import unquote, urlsplit
import webbrowser


_RANGE = re.compile(r"bytes=(\d*)-(\d*)", re.ASCII)
_TYPES = {".html": "text/html; charset=utf-8", ".json": "application/json", ".mp4": "video/mp4"}


def _byte_range(header: str, size: int) -> tuple[int, int]:
    match = _RANGE.fullmatch(header.strip())
    if not match or size <= 0 or not any(match.groups()):
        raise ValueError("invalid byte range")
    first, last = match.groups()
    if not first:
        suffix = int(last)
        if suffix <= 0:
            raise ValueError("empty suffix range")
        return max(0, size - suffix), size - 1
    start = int(first)
    end = min(size - 1, int(last)) if last else size - 1
    if start > end:
        raise ValueError("unsatisfiable byte range")
    return start, end


def serve_demo(
    *, routes: Mapping[str, Path], port: int, demo_route: str, open_browser: bool = False,
) -> None:
    """Serve configured files only. A port of zero selects an available port."""
    files = {unquote(route): path.resolve() for route, path in routes.items()}
    if unquote(demo_route) not in files:
        raise ValueError("the demo page must have a configured route")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            self._serve(send_body=True)

        def do_HEAD(self) -> None:
            self._serve(send_body=False)

        def _serve(self, *, send_body: bool) -> None:
            path = files.get(unquote(urlsplit(self.path).path))
            if path is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                source = path.open("rb")
            except OSError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                with source:
                    size = source.seek(0, 2)
                    start, end = 0, size - 1
                    range_header = self.headers.get("Range")
                    if range_header is not None:
                        try:
                            start, end = _byte_range(range_header, size)
                        except ValueError:
                            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                            self.send_header("Content-Range", f"bytes */{size}")
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                            return
                    partial = range_header is not None
                    remaining = end - start + 1
                    content_type = _TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
                    self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
                    self.send_header("Content-Type", content_type or "application/octet-stream")
                    self.send_header("Content-Length", str(remaining))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Cache-Control", "no-store")
                    if partial:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    if send_body:
                        source.seek(start)
                        while remaining:
                            chunk = source.read(min(remaining, 64 * 1024))
                            if not chunk:
                                return
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                return

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        url = f"http://127.0.0.1:{server.server_port}{demo_route}"
        print(url, flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
