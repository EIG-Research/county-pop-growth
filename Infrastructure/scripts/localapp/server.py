"""Loopback HTTP server and request-handler base for the local apps.

The app is bound to 127.0.0.1, which stops remote clients but not a web page the user
already has open: any site can send a request to `http://127.0.0.1:<port>`. So every
request must carry an `Origin`, or without one a `Host`, naming a loopback host on the
exact bound port. Every response carries the security headers and a CSP with no inline
script, and a request body over the cap is refused before it is read.
"""

from __future__ import annotations

import errno
import json
import os
import socket
import socketserver
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_BODY_BYTES = 64 * 1024
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; connect-src 'self'; "
                                "img-src 'self' blob:; style-src 'unsafe-inline'; "
                                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
}


def browser_skip_reason() -> str | None:
    """Why a browser must not be opened here, or None.

    On a Linux machine with no display, `webbrowser` falls back to a text browser (lynx,
    w3m) that takes over the terminal the agent is running in; under CI nobody is looking.
    """
    if os.environ.get("CI"):
        return "CI is set"
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY")
                                                 or os.environ.get("WAYLAND_DISPLAY")):
        return "no display (neither DISPLAY nor WAYLAND_DISPLAY is set)"
    return None


class PortInUseError(OSError):
    """The requested port is taken; the message says what to do instead."""


class LoopbackServer(ThreadingHTTPServer):
    """A threading server on 127.0.0.1 with a listen queue deep enough for a burst.

    The standard library's backlog is 5; a full backlog resets new connections on Windows
    and can on Linux, so a burst of saves or image loads would lose requests. Handler
    threads are daemons, so a stuck request never keeps a stopped server alive.
    """

    request_queue_size = 128
    daemon_threads = True
    # On Windows, SO_REUSEADDR lets a second socket bind a port another is already listening
    # on, so a second server would share the port instead of failing with PortInUseError.
    # Windows gets exclusive use instead. POSIX keeps SO_REUSEADDR, which there only permits
    # rebinding a port left in TIME_WAIT by a stopped server.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        # `HTTPServer.server_bind` resolves the host with `socket.getfqdn`, which blocks for
        # about 35 s on some macOS hosts. The host is always 127.0.0.1, so bind without it.
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    def __init__(self, port: int, handler_class: type[BaseHTTPRequestHandler]) -> None:
        try:
            super().__init__(("127.0.0.1", port), handler_class)
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", -1)):
                raise PortInUseError(
                    exc.errno, f"port {port} on 127.0.0.1 is already in use; stop the "
                               f"program using it, or pass --port 0 to pick a free port"
                ) from None
            raise
        self._serving = threading.Event()

    def service_actions(self) -> None:
        """Called by `serve_forever` on every pass of its loop: requests are being served."""
        self._serving.set()

    def open_browser_when_serving(self) -> str | None:
        """Open the app in a browser once `serve_forever` is running, on a daemon thread.

        `webbrowser.open` can block until the browser exits (a `BROWSER` command, a text
        browser), so opening before serving, on the serving thread, left every request
        waiting on it. Returns a note to print when no browser is opened, else None.
        """
        reason = browser_skip_reason()
        if reason:
            return f"Not opening a browser: {reason}. Open {self.url} yourself."

        def run() -> None:
            if self._serving.wait(30):
                try:
                    webbrowser.open(self.url)
                except Exception:  # noqa: BLE001 - a browser failure never stops the app
                    pass

        threading.Thread(target=run, daemon=True, name="open-browser").start()
        return None

    @property
    def port(self) -> int:
        return self.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"


class LoopbackHandler(BaseHTTPRequestHandler):
    """Origin and Host checks, headers, the body cap, JSON helpers, static files, routing.

    Subclasses set `static` ({route: (file, content type)}) and override `handle_get` and
    `handle_post`; routes are matched on the path alone, so a query string still routes.
    """

    protocol_version = "HTTP/1.1"
    # Seconds a connection may sit idle or stall mid-request before it is dropped, so a
    # client that connects and sends nothing cannot hold a handler thread for ever.
    timeout = 30
    static: dict[str, tuple[Path, str]] = {}
    max_body_bytes = MAX_BODY_BYTES
    security_headers = SECURITY_HEADERS

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # the terminal belongs to the user

    def end_headers(self) -> None:
        """Every response carries the security headers and CSP, including the standard
        library's own `send_error` pages, such as the 501 for HEAD or OPTIONS."""
        for key, value in self.security_headers.items():
            self.send_header(key, value)
        super().end_headers()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    @property
    def route(self) -> str:
        return urlsplit(self.path).path

    def origin_ok(self) -> bool:
        """`Origin` must name loopback on this port; without one, `Host` must."""
        origin = self.headers.get("Origin")
        parts = urlsplit(origin if origin else f"//{self.headers.get('Host') or ''}")
        try:
            host, port = parts.hostname, parts.port  # `port` raises on a malformed value
        except ValueError:
            return False
        return host is not None and host.lower() in LOOPBACK_HOSTS and (port or 0) == self.port

    def send_bytes(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj: Any, code: int = 200) -> None:
        self.send_bytes(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def refuse(self, code: int, error: str, **extra: Any) -> None:
        self.send_json({"ok": False, "error": error, **extra}, code)

    def read_body(self) -> bytes | None:
        """The body, or None after replying 400 or 413. It is read before any other reply,
        because on a keep-alive connection an unread body becomes the next request."""
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw) if raw is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self.refuse(400, "Content-Length is missing or not a number")
            return None
        if length > self.max_body_bytes:
            self.close_connection = True
            self.refuse(413, f"body over {self.max_body_bytes} bytes")
            return None
        return self.rfile.read(length) if length else b""

    def json_object(self, body: bytes) -> dict | None:
        """The body as a JSON object, or None after replying 400."""
        try:
            payload = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.refuse(400, "bad json")
            return None
        if not isinstance(payload, dict):
            self.refuse(400, "the body must be a JSON object")
            return None
        return payload

    def do_GET(self) -> None:  # noqa: N802
        if not self.origin_ok():
            return self.refuse(403, "forbidden origin")
        if self.route in self.static:
            path, ctype = self.static[self.route]
            return self.send_bytes(200, Path(path).read_bytes(), ctype)
        return self.handle_get(self.route)

    def do_POST(self) -> None:  # noqa: N802
        body = self.read_body()
        if body is None:
            return None
        if not self.origin_ok():
            return self.refuse(403, "forbidden origin")
        return self.handle_post(self.route, body)

    def handle_get(self, route: str) -> None:
        self.refuse(404, "not found")

    def handle_post(self, route: str, body: bytes) -> None:
        self.refuse(404, "not found")

    def _refuse_method(self) -> None:
        self.refuse(405, "method not allowed")

    do_PUT = do_DELETE = do_PATCH = _refuse_method  # noqa: N815

