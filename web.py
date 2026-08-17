from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import json
import secrets
import socket
import sys
import threading
import time
import traceback
from collections import OrderedDict
from contextlib import suppress
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib import resources
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import urlsplit


_CLIENT_DISCONNECT_ERRNOS = frozenset(
    value
    for value in (
        errno.EPIPE,
        errno.ECONNRESET,
        errno.ECONNABORTED,
        errno.ETIMEDOUT,
        errno.ENOTCONN,
    )
    if value is not None
)

_COMMON_SECURITY_HEADERS = {
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}

_CSP = (
    "default-src 'none'; "
    "style-src 'self'; script-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; font-src 'self'; "
    "base-uri 'none'; frame-ancestors 'none'; form-action 'none'; object-src 'none'"
)


@dataclass(frozen=True, slots=True)
class CachedResponse:
    body: bytes
    etag: str
    content_type: str = "application/json; charset=utf-8"


@dataclass(slots=True)
class _ClientState:
    tokens: float
    last_refill: float
    active: int = 0
    violations: int = 0
    blocked_until: float = 0.0
    last_seen: float = 0.0


class ClientGuard:
    """Bounded per-IP concurrency and token-bucket protection."""

    def __init__(
        self,
        *,
        rate_per_second: float,
        burst: int,
        per_ip_connections: int,
        temporary_block_seconds: int,
        max_tracked_clients: int,
    ) -> None:
        self.rate_per_second = rate_per_second
        self.burst = float(burst)
        self.per_ip_connections = per_ip_connections
        self.temporary_block_seconds = temporary_block_seconds
        self.max_tracked_clients = max_tracked_clients
        self._clients: OrderedDict[str, _ClientState] = OrderedDict()
        self._lock = threading.Lock()
        self._accepted = 0
        self._rejected = 0
        self._blocked = 0
        self._active = 0

    def acquire(self, client_ip: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            state = self._clients.get(client_ip)
            if state is None:
                self._make_room()
                state = _ClientState(tokens=self.burst, last_refill=now, last_seen=now)
                self._clients[client_ip] = state
            else:
                self._clients.move_to_end(client_ip)

            state.last_seen = now
            if state.blocked_until > now:
                self._rejected += 1
                self._blocked += 1
                return False, max(1, int(state.blocked_until - now + 0.999))

            elapsed = max(0.0, now - state.last_refill)
            state.tokens = min(self.burst, state.tokens + elapsed * self.rate_per_second)
            state.last_refill = now

            if state.active >= self.per_ip_connections or state.tokens < 1.0:
                state.violations += 1
                self._rejected += 1
                if state.violations >= 12:
                    state.blocked_until = now + self.temporary_block_seconds
                    state.violations = 0
                    self._blocked += 1
                    return False, self.temporary_block_seconds
                return False, 1

            state.tokens -= 1.0
            state.active += 1
            state.violations = max(0, state.violations - 1)
            self._accepted += 1
            self._active += 1
            return True, 0

    def release(self, client_ip: str) -> None:
        with self._lock:
            state = self._clients.get(client_ip)
            if state is not None and state.active > 0:
                state.active -= 1
            self._active = max(0, self._active - 1)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "accepted_requests": self._accepted,
                "rejected_requests": self._rejected,
                "temporary_blocks": self._blocked,
                "active_requests": self._active,
                "tracked_clients": len(self._clients),
            }

    def _make_room(self) -> None:
        if len(self._clients) < self.max_tracked_clients:
            return
        for key, state in list(self._clients.items()):
            if state.active == 0:
                del self._clients[key]
                return
        self._clients.popitem(last=False)


def _is_expected_disconnect(exc: BaseException | None) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
        return True
    return isinstance(exc, OSError) and exc.errno in _CLIENT_DISCONNECT_ERRNOS


def _asset(name: str, content_type: str) -> CachedResponse:
    body = resources.files("endstone_show_status.webui").joinpath(name).read_bytes()
    digest = hashlib.sha256(body).hexdigest()[:20]
    return CachedResponse(body=body, etag=f'"{digest}"', content_type=content_type)


_STATIC_RESPONSES = {
    "/": _asset("index.html", "text/html; charset=utf-8"),
    "/assets/app.css": _asset("app.css", "text/css; charset=utf-8"),
    "/assets/app.js": _asset("app.js", "text/javascript; charset=utf-8"),
    "/assets/favicon.svg": _asset("favicon.svg", "image/svg+xml; charset=utf-8"),
}


class PublicStatusHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    block_on_close = False
    request_queue_size = 128

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        plugin: Any,
        max_connections: int,
        per_ip_connections: int,
        socket_timeout: float,
        rate_limit_per_second: float,
        rate_limit_burst: int,
        temporary_block_seconds: int,
        max_tracked_clients: int,
        allow_indexing: bool,
        auth_username: str = "status",
        auth_password: str = "",
    ) -> None:
        self.plugin = plugin
        self.socket_timeout = socket_timeout
        self.allow_indexing = allow_indexing
        self.auth_username = auth_username
        self.auth_password = auth_password
        self.stopping = threading.Event()
        self._request_slots = threading.BoundedSemaphore(max_connections)
        self.guard = ClientGuard(
            rate_per_second=rate_limit_per_second,
            burst=rate_limit_burst,
            per_ip_connections=per_ip_connections,
            temporary_block_seconds=temporary_block_seconds,
            max_tracked_clients=max_tracked_clients,
        )
        super().__init__(server_address, handler_class)

    @staticmethod
    def client_ip(client_address: tuple[Any, ...]) -> str:
        return str(client_address[0]) if client_address else "unknown"

    def process_request(self, request: socket.socket, client_address: tuple[Any, ...]) -> None:
        if not self._request_slots.acquire(blocking=False):
            self._reject_socket(request, HTTPStatus.SERVICE_UNAVAILABLE, 1)
            return

        client_ip = self.client_ip(client_address)
        allowed, retry_after = self.guard.acquire(client_ip)
        if not allowed:
            self._request_slots.release()
            self._reject_socket(request, HTTPStatus.TOO_MANY_REQUESTS, retry_after)
            return

        try:
            super().process_request(request, client_address)
        except BaseException:
            self.guard.release(client_ip)
            self._request_slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple[Any, ...]) -> None:
        client_ip = self.client_ip(client_address)
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.guard.release(client_ip)
            self._request_slots.release()

    def _reject_socket(self, request: socket.socket, status: HTTPStatus, retry_after: int) -> None:
        body = f"{status.value} {status.phrase}\n".encode("ascii")
        response = (
            f"HTTP/1.0 {status.value} {status.phrase}\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Retry-After: {max(1, retry_after)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body
        with suppress(OSError):
            request.settimeout(0.25)
            request.sendall(response)
        with suppress(OSError):
            request.shutdown(socket.SHUT_RDWR)
        self.close_request(request)

    def handle_error(self, request: socket.socket, client_address: tuple[Any, ...]) -> None:
        exc = sys.exc_info()[1]
        if _is_expected_disconnect(exc):
            return
        if self.stopping.is_set() and isinstance(exc, OSError):
            return
        self.report_current_exception(
            f"HTTP request from {self.client_ip(client_address)} failed"
        )

    def report_current_exception(self, message: str) -> None:
        details = "".join(traceback.format_exception(*sys.exc_info())).rstrip()
        self.plugin.log_error(f"{message}\n{details}")


class StatusRequestHandler(BaseHTTPRequestHandler):
    server: PublicStatusHTTPServer
    server_version = "EndstoneShowStatus/0.2"
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.server.socket_timeout)

    def do_GET(self) -> None:
        self._dispatch(head_only=False)

    def do_HEAD(self) -> None:
        self._dispatch(head_only=True)

    def do_POST(self) -> None:
        self._method_not_allowed()

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST
    do_OPTIONS = do_POST
    do_TRACE = do_POST
    do_CONNECT = do_POST

    def _method_not_allowed(self) -> None:
        self._send_bytes(
            HTTPStatus.METHOD_NOT_ALLOWED,
            b"Method Not Allowed\n",
            "text/plain; charset=utf-8",
            head_only=False,
            extra_headers={"Allow": "GET, HEAD"},
            cache_control="no-store",
        )

    def _dispatch(self, *, head_only: bool) -> None:
        if not self._is_authorized():
            self._send_bytes(
                HTTPStatus.UNAUTHORIZED,
                b"Authentication required\n",
                "text/plain; charset=utf-8",
                head_only=head_only,
                extra_headers={
                    "WWW-Authenticate": 'Basic realm="Endstone Status", charset="UTF-8"',
                    "Vary": "Authorization",
                },
                cache_control="no-store",
            )
            return

        if len(self.path) > 2048:
            self._send_text(HTTPStatus.REQUEST_URI_TOO_LONG, "URI Too Long\n", head_only=head_only)
            return

        content_length = self.headers.get("Content-Length")
        if content_length not in {None, "", "0"}:
            self._send_text(HTTPStatus.BAD_REQUEST, "GET request body is not accepted\n", head_only=head_only)
            return

        try:
            parsed = urlsplit(self.path)
            path = parsed.path
        except ValueError:
            self._send_text(HTTPStatus.BAD_REQUEST, "Bad Request\n", head_only=head_only)
            return

        static = _STATIC_RESPONSES.get(path)
        if static is not None:
            cache_control = "no-cache" if path == "/" else "public, max-age=86400"
            self._send_cached(HTTPStatus.OK, static, head_only=head_only, cache_control=cache_control)
            return

        if path == "/api/v1/status":
            self._send_cached(
                HTTPStatus.OK,
                self.server.plugin.get_cached_status_response(),
                head_only=head_only,
                cache_control="no-cache, must-revalidate",
            )
            return

        if path == "/api/v1/history":
            self._send_cached(
                HTTPStatus.OK,
                self.server.plugin.get_cached_history_response(),
                head_only=head_only,
                cache_control="no-cache, must-revalidate",
            )
            return

        if path == "/data":
            self._send_cached(
                HTTPStatus.OK,
                self.server.plugin.get_cached_legacy_response(),
                head_only=head_only,
                cache_control="no-cache, must-revalidate",
            )
            return

        if path == "/healthz":
            body = b'{"ok":true}' if self.server.plugin.is_running else b'{"ok":false}'
            self._send_bytes(
                HTTPStatus.OK if self.server.plugin.is_running else HTTPStatus.SERVICE_UNAVAILABLE,
                body,
                "application/json; charset=utf-8",
                head_only=head_only,
                cache_control="no-store",
            )
            return

        if path == "/robots.txt":
            text = "User-agent: *\nAllow: /\n" if self.server.allow_indexing else "User-agent: *\nDisallow: /\n"
            self._send_text(HTTPStatus.OK, text, head_only=head_only, cache_control="public, max-age=3600")
            return

        self._send_text(HTTPStatus.NOT_FOUND, "Not Found\n", head_only=head_only)


    def _is_authorized(self) -> bool:
        password = self.server.auth_password
        if not password:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            username, supplied_password = decoded.split(":", 1)
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return False
        return secrets.compare_digest(username, self.server.auth_username) and secrets.compare_digest(
            supplied_password, password
        )

    def _send_cached(
        self,
        status: HTTPStatus,
        response: CachedResponse,
        *,
        head_only: bool,
        cache_control: str,
    ) -> None:
        if self.headers.get("If-None-Match") == response.etag:
            self._send_bytes(
                HTTPStatus.NOT_MODIFIED,
                b"",
                response.content_type,
                head_only=True,
                extra_headers={"ETag": response.etag},
                cache_control=cache_control,
            )
            return
        self._send_bytes(
            status,
            response.body,
            response.content_type,
            head_only=head_only,
            extra_headers={"ETag": response.etag},
            cache_control=cache_control,
        )

    def _send_text(
        self,
        status: HTTPStatus,
        text: str,
        *,
        head_only: bool,
        cache_control: str = "no-store",
    ) -> None:
        self._send_bytes(
            status,
            text.encode("utf-8"),
            "text/plain; charset=utf-8",
            head_only=head_only,
            cache_control=cache_control,
        )

    def _send_bytes(
        self,
        status: HTTPStatus,
        body: bytes,
        content_type: str,
        *,
        head_only: bool,
        extra_headers: dict[str, str] | None = None,
        cache_control: str,
    ) -> None:
        try:
            self.send_response(int(status))
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("Connection", "close")
            for key, value in _COMMON_SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.send_header("Content-Security-Policy", _CSP)
            if not self.server.allow_indexing:
                self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            if not head_only and body:
                self.wfile.write(body)
        except OSError as exc:
            if _is_expected_disconnect(exc):
                self.close_connection = True
                return
            raise

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        try:
            status = HTTPStatus(code)
        except ValueError:
            status = HTTPStatus.BAD_REQUEST
        self._send_text(status, f"{status.value} {message or status.phrase}\n", head_only=False)

    def log_message(self, format: str, *args: Any) -> None:
        return


def json_response(payload: Any, revision: int) -> CachedResponse:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return CachedResponse(body=body, etag=f'W/"{revision}"')
