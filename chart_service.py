"""Loopback-only chart session service for dsh_kline.

The MCP process owns this HTTP server. Chart payloads stay in memory and are
addressed by random session IDs; no API credentials or market rows are written
to disk.
"""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

from core.calc import calc_range
from tools.fetch import (
    fetch_candles,
    fetch_comparison_candles,
    fetch_market_ticker,
    fetch_security_workspace,
    search_symbols,
    symbol_directory,
)


ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT / ".runtime"
RUNTIME_SESSION_FILE = RUNTIME_DIR / "chart-session.json"
SERVER_VERSION = "0.1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 8 * 1024 * 1024
SESSION_TTL_SECONDS = 6 * 60 * 60
MAX_SESSIONS = 128
CHART_API_ACTIONS = frozenset(
    {
        "calc_range",
        "fetch_candles",
        "fetch_comparison_candles",
        "fetch_security_workspace",
        "market_ticker",
        "search_symbols",
        "symbol_directory",
    }
)


@dataclass(frozen=True)
class ChartSession:
    payload: dict[str, Any]
    created_at: float


class ChartSessionStore:
    def __init__(self, *, ttl_seconds: int = SESSION_TTL_SECONDS, max_sessions: int = MAX_SESSIONS) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self._items: OrderedDict[str, ChartSession] = OrderedDict()
        self._lock = threading.Lock()

    def create(self, payload: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(24)
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            self._items[token] = ChartSession(payload=payload, created_at=now)
            while len(self._items) > self.max_sessions:
                self._items.popitem(last=False)
        return token

    def get(self, token: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            session = self._items.get(token)
            if session is None:
                return None
            self._items.move_to_end(token)
            return session.payload

    def _prune_locked(self, now: float) -> None:
        expired = [key for key, value in self._items.items() if now - value.created_at > self.ttl_seconds]
        for key in expired:
            self._items.pop(key, None)


def _tool_dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "symbol_directory":
        return symbol_directory(force_refresh=bool(args.get("refresh") or args.get("force_refresh")))
    routes: dict[str, Callable[..., dict[str, Any]]] = {
        "fetch_candles": fetch_candles,
        "fetch_comparison_candles": fetch_comparison_candles,
        "fetch_security_workspace": fetch_security_workspace,
        "market_ticker": fetch_market_ticker,
        "search_symbols": search_symbols,
        "calc_range": calc_range,
    }
    function = routes.get(name)
    if function is None:
        return {"ok": False, "error": "unsupported_chart_action", "message": f"unsupported action: {name}"}
    try:
        return function(**args)
    except TypeError as exc:
        return {"ok": False, "error": "invalid_arguments", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "chart_action_failed", "message": str(exc)}


class ChartRequestHandler(BaseHTTPRequestHandler):
    server_version = "dsh-kline-chart/0.1.0"

    @property
    def session_store(self) -> ChartSessionStore:
        return self.server.session_store  # type: ignore[attr-defined, no-any-return]

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/healthz":
            self._send_json({"ok": True, "service": "dsh_kline_chart", "version": SERVER_VERSION})
            return
        if path.startswith("/api/session/"):
            token = path.removeprefix("/api/session/").strip("/")
            payload = self.session_store.get(token)
            if payload is None:
                self._send_json(
                    {"ok": False, "error": "chart_session_not_found", "message": "Chart session expired or does not exist."},
                    status=HTTPStatus.NOT_FOUND,
                )
                return
            self._send_json({"ok": True, "session": token, "payload": payload})
            return
        self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if not path.startswith("/api/tools/"):
            self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            size = 0
        if size <= 0 or size > MAX_REQUEST_BYTES:
            self._send_json({"ok": False, "error": "invalid_request_size"}, status=HTTPStatus.BAD_REQUEST)
            return
        try:
            body = json.loads(self.rfile.read(size))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json({"ok": False, "error": "invalid_json"}, status=HTTPStatus.BAD_REQUEST)
            return
        if not isinstance(body, dict):
            self._send_json({"ok": False, "error": "invalid_arguments"}, status=HTTPStatus.BAD_REQUEST)
            return
        result = _tool_dispatch(path.removeprefix("/api/tools/").strip("/"), body)
        self._send_json({"structuredContent": result, "isError": result.get("ok") is False})

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_bytes(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json; charset=utf-8",
            status=status,
        )

    def _send_bytes(self, payload: bytes, content_type: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
        )
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


class ChartHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], store: ChartSessionStore) -> None:
        self.session_store = store
        super().__init__(address, ChartRequestHandler)


class ChartService:
    def __init__(self, host: str, port: int) -> None:
        self.store = ChartSessionStore()
        self.httpd = ChartHTTPServer((host, port), self.store)
        self.host = host
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="dsh-kline-chart", daemon=True)
        self.thread.start()

    def publish(self, payload: dict[str, Any]) -> tuple[str, str]:
        token = self.store.create(payload)
        service_url = f"http://{self.host}:{self.port}"
        _write_runtime_session(token, service_url, payload)
        return token, service_url


def _write_runtime_session(token: str, service_url: str, payload: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    document = {
        "ok": True,
        "process_id": os.getpid(),
        "session": token,
        "service_url": service_url,
        "symbol": str(payload.get("symbol") or ""),
        "name": str(payload.get("name") or ""),
        "published_at": int(time.time()),
    }
    descriptor, temp_name = tempfile.mkstemp(prefix="chart-session-", suffix=".json", dir=RUNTIME_DIR)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, RUNTIME_SESSION_FILE)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


_service: ChartService | None = None
_service_lock = threading.Lock()


def ensure_chart_service() -> ChartService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            host = os.environ.get("DSH_KLINE_CHART_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
            if host not in {"127.0.0.1", "localhost"}:
                raise ValueError("DSH_KLINE_CHART_HOST must be a loopback address")
            configured_port = os.environ.get("DSH_KLINE_CHART_PORT", "").strip()
            raw_port = configured_port or str(DEFAULT_PORT)
            port = int(raw_port)
            if not 0 <= port <= 65535:
                raise ValueError("DSH_KLINE_CHART_PORT must be between 0 and 65535")
            try:
                _service = ChartService(host, port)
            except OSError:
                if port == 0:
                    raise
                _service = ChartService(host, 0)
    return _service


def publish_chart(payload: dict[str, Any]) -> tuple[str, str]:
    return ensure_chart_service().publish(payload)
