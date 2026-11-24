"""Lightweight localhost-only HTTP Range Media Streamer (127.0.0.1).

Serves video/audio/storyboard files inside D:\\CLIP\\temp_cache with HTTP 206
Range support so the Antigravity MCP App side pane can stream & seek 60-minute
videos smoothly without hitting the 1 MiB MCP CallToolResult payload limit.
"""

from __future__ import annotations

import mimetypes
import os
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .project_store import get_cache_root

_SERVER_LOCK = threading.Lock()
_ACTIVE_PORT: int | None = None


class _RangeRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        # Silence HTTP logs so stdio MCP JSON-RPC stream on stdout/stderr stays clean
        return

    def _send_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Range, Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_HEAD(self) -> None:
        self._serve_file(send_body=False)

    def do_GET(self) -> None:
        self._serve_file(send_body=True)

    def _serve_file(self, send_body: bool = True) -> None:
        rel_path = unquote(self.path.split("?", 1)[0]).lstrip("/")
        cache_root = get_cache_root().resolve()
        target = (cache_root / rel_path).resolve()

        # Strict path traversal guard: only serve files inside RECAP_CACHE_ROOT
        try:
            target.relative_to(cache_root)
        except ValueError:
            self.send_error(403, "Forbidden")
            return

        if not target.is_file():
            self.send_error(404, "File not found")
            return

        file_size = target.stat().st_size
        ctype, _ = mimetypes.guess_type(str(target))
        ctype = ctype or "application/octet-stream"

        range_header = self.headers.get("Range")
        start = 0
        end = file_size - 1
        status = 200

        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if m:
                s_str, e_str = m.groups()
                if s_str:
                    start = int(s_str)
                if e_str:
                    end = min(file_size - 1, int(e_str))
                if start > end or start >= file_size:
                    self.send_response(416)
                    self._send_cors()
                    self.send_header("Content-Range", f"bytes */{file_size}")
                    self.end_headers()
                    return
                status = 206

        length = end - start + 1
        self.send_response(status)
        self._send_cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(length))
        self.end_headers()

        if not send_body:
            return

        with target.open("rb") as f:
            f.seek(start)
            remaining = length
            chunk_size = 64 * 1024
            while remaining > 0:
                data = f.read(min(chunk_size, remaining))
                if not data:
                    break
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(data)


def ensure_streamer_running() -> int:
    global _ACTIVE_PORT
    with _SERVER_LOCK:
        if _ACTIVE_PORT is not None:
            return _ACTIVE_PORT
        for port in range(18920, 18935):
            try:
                httpd = ThreadingHTTPServer(("127.0.0.1", port), _RangeRequestHandler)
                t = threading.Thread(target=httpd.serve_forever, name="recap-media-streamer", daemon=True)
                t.start()
                _ACTIVE_PORT = port
                return port
            except OSError:
                continue
        # Fallback OS-assigned port
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _RangeRequestHandler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, name="recap-media-streamer", daemon=True)
        t.start()
        _ACTIVE_PORT = port
        return port


def media_url_for_path(file_path: str) -> str:
    if not file_path:
        return ""
    p = Path(file_path)
    if not p.exists():
        return ""
    cache_root = get_cache_root().resolve()
    try:
        rel = p.resolve().relative_to(cache_root).as_posix()
    except ValueError:
        return ""
    port = ensure_streamer_running()
    mtime = int(p.stat().st_mtime * 1000)
    return f"http://127.0.0.1:{port}/{rel}?v={mtime}"
