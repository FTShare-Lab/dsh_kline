"""Loopback-only chart session service for dsh_kline.

The MCP process owns this HTTP server. Chart payloads stay in memory and are
addressed by random session IDs. API credentials are handled separately by
the provider adapter and never enter chart-session files.
"""

from __future__ import annotations

import json
import hmac
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

from core.calc import (
    DEFAULT_ATR_PERIOD,
    DEFAULT_BOLL_PERIOD,
    DEFAULT_BOLL_STD,
    DEFAULT_MA_PERIODS,
    DEFAULT_RSI_PERIOD,
    DEFAULT_VOLUME_MA,
    calc_range,
)
from tools.calc import run_calc_metrics
from core.rows import validate_rows, RowsValidationError
from tools.draw import draw_kline
from tools.fetch import (
    configure_ftshare_api_key,
    fetch_candles,
    fetch_comparison_candles,
    fetch_market_ticker,
    fetch_security_workspace,
    ftshare_capabilities,
    ftshare_index_kline_available,
    ftshare_status,
    search_symbols,
    symbol_directory,
    test_ftshare_connection,
)


ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT / ".runtime"
# The same installation can serve multiple Harness profiles at once. Never
# let a temporary/test MCP replace the live host's service locator. Direct
# stdio launches inherit the Harness PID as their parent (the runner execs).
HOST_PROCESS_ID = int(os.environ.get("DSH_KLINE_HOST_PID") or os.getppid())
if HOST_PROCESS_ID <= 0:
    raise ValueError("DSH_KLINE_HOST_PID must be a positive process ID")
RUNTIME_SESSION_FILE = RUNTIME_DIR / "services" / f"{HOST_PROCESS_ID}.json"
SERVER_VERSION = "0.1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_REQUEST_BYTES = 8 * 1024 * 1024
SESSION_TTL_SECONDS = 6 * 60 * 60
MAX_SESSIONS = 128
CHART_API_ACTIONS = frozenset(
    {
        "analyze_kline",
        "analyze_key_levels",
        "calc_range",
        "fetch_candles",
        "fetch_comparison_candles",
        "fetch_security_workspace",
        "market_ticker",
        "search_symbols",
        "symbol_directory",
        "data_source_status",
        "configure_ftshare",
        "test_ftshare_connection",
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


def _http_key_levels(args: dict[str, Any]) -> dict[str, Any]:
    """Analyze the displayed bars only; never fetch or replace market data."""
    from server import _support_resistance_marks

    raw = args.get("rows")
    if not isinstance(raw, list) or len(raw) > 12000:
        return {"ok": False, "error": "invalid_rows", "message": "请提供不超过 12000 根的 K 线数据。"}
    try:
        rows = validate_rows(raw, min_len=1)
    except RowsValidationError:
        return {"ok": False, "error": "invalid_rows", "message": "K 线数据无效，请重新加载行情。"}
    if len(rows) < 5:
        return {"ok": False, "error": "insufficient_candles", "message": "关键点位分析至少需要 5 根有效 K 线，请扩大时间范围。"}
    metrics = run_calc_metrics(rows, metrics=["support_resistance"])
    marks = [{"type": "TEXT_MARKER", **mark} for mark in _support_resistance_marks(metrics)]
    return {"ok": True, "symbol": str(args.get("symbol") or ""),
            "count": len(rows), "chartCommands": marks, "metrics": metrics,
            "status": "ready" if marks else "no_levels"}


def _http_analyze_kline(args: dict[str, Any]) -> dict[str, Any]:
    """analyze_kline over the loopback chart API (key-level re-analysis).

    The MCP module implements the authoritative analyze pipeline; this module is
    imported by that module, so its helpers are loaded lazily at request time.
    Only the loopback service publishes chart sessions, so this action redraws
    through the returned chart payload without touching the shared session.
    """
    try:
        from server import (  # noqa: PLC0415
            _normalized_indicators,
            _normalized_ma_periods,
            _resolve_symbol_input,
            _support_resistance_marks,
            _validate_interval,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "chart_action_failed", "message": f"analyze_kline unavailable: {exc}"}

    def _positive(value: Any, fallback: float, minimum: float, maximum: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return fallback
        if parsed < minimum:
            return minimum
        if parsed > maximum:
            return maximum
        return parsed

    try:
        symbol = str(args.get("symbol") or "").strip()
        if not symbol:
            return {"ok": False, "error": "invalid_arguments", "message": "symbol is required"}
        normalized_interval, interval_error = _validate_interval(str(args.get("interval") or "day"))
        if interval_error:
            return {"ok": False, **interval_error}
        interval = normalized_interval or "day"
        resolved_symbol, resolved_name, symbol_error = _resolve_symbol_input(symbol)
        if symbol_error:
            return {"ok": False, **symbol_error}
        adjust = str(args.get("adjust") or "none").strip().lower()
        if adjust not in {"none", "forward", "backward"}:
            adjust = "none"
        interval_value = int(_positive(args.get("interval_value"), 1, 1, 240))
        raw_sessions = args.get("session_count")
        session_count = int(_positive(raw_sessions, 5, 1, 10)) if raw_sessions is not None else None
        requested = max(2, min(int(args.get("limit") or 60), 4000))
        fetch_limit = requested if interval == "minute" else min(4000, max(requested, int(requested * 1.8)))
        fetched = fetch_candles(
            resolved_symbol or symbol,
            interval=interval,
            interval_value=interval_value,
            session_count=session_count,
            limit=fetch_limit,
            adjust=adjust,
        )
        if not fetched.get("ok"):
            return dict(fetched)
        rows = list(fetched.get("rows") or [])[-requested:]
        if len(rows) < 2:
            return {"ok": False, "error": "insufficient_candles", "message": "fewer than two candles", "symbol": symbol}

        active_indicators, unknown_indicators = _normalized_indicators(args.get("indicators"))
        periods = _normalized_ma_periods(args.get("ma_periods"))
        requested_metrics = [str(value).lower() for value in args["metrics"]] if isinstance(args.get("metrics"), list) else ["rsi"]
        should_mark_levels = bool(args.get("mark_support_resistance")) or "support_resistance" in requested_metrics
        if args.get("mark_support_resistance") and "support_resistance" not in requested_metrics:
            requested_metrics.append("support_resistance")
        boll_period = int(_positive(args.get("boll_period"), DEFAULT_BOLL_PERIOD, 2, 200))
        boll_std = float(_positive(args.get("boll_std"), DEFAULT_BOLL_STD, 0.5, 5.0))
        rsi_period = int(_positive(args.get("rsi_period"), DEFAULT_RSI_PERIOD, 2, 100))
        atr_period = int(_positive(args.get("atr_period"), DEFAULT_ATR_PERIOD, 2, 100))
        volume_ma = int(_positive(args.get("volume_ma"), DEFAULT_VOLUME_MA, 2, 200))
        metric_data = run_calc_metrics(
            rows,
            metrics=requested_metrics,
            rsi_period=rsi_period,
            boll_period=boll_period,
            boll_std=boll_std,
            atr_period=atr_period,
            volume_ma=volume_ma,
            ma_periods=periods,
        )
        analysis_marks = _support_resistance_marks(metric_data) if should_mark_levels else []
        payload = draw_kline(
            rows,
            indicators=active_indicators,
            indicators_explicit=args.get("indicators") is not None,
            ma_periods=periods,
            marks=analysis_marks,
            symbol=str(fetched.get("symbol") or resolved_symbol or symbol),
            name=str(fetched.get("name") or resolved_name or symbol),
            data_source=str(fetched.get("source") or "ftshare"),
            interval=interval,
            boll_period=boll_period,
            boll_std=boll_std,
            volume_ma=volume_ma,
            rsi_period=rsi_period,
            atr_period=atr_period,
        )
        previous = float(rows[-2]["close"])
        latest = dict(rows[-1])
        latest["change"] = round(float(latest["close"]) - previous, 6)
        latest["change_pct"] = round((float(latest["close"]) / previous - 1) * 100, 4) if previous else None
        payload.update(
            {
                "ok": True,
                "workflow": "chart_api_analyze_key_levels",
                "adjust": adjust,
                "source": str(fetched.get("source") or "ftshare"),
                "count": len(rows),
                "fetched_count": len(fetched.get("rows") or []),
                "latest": latest,
                "metrics": metric_data,
                "warnings": ([f"ignored unsupported indicators: {', '.join(unknown_indicators)}"] if unknown_indicators else []),
            }
        )
        return payload
    except TypeError as exc:
        return {"ok": False, "error": "invalid_arguments", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "chart_action_failed", "message": str(exc)}


def _tool_dispatch(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "analyze_key_levels":
        return _http_key_levels(args)
    if name == "analyze_kline":
        return _http_analyze_kline(args)
    if name == "symbol_directory":
        return symbol_directory(force_refresh=bool(args.get("refresh") or args.get("force_refresh")))
    if name == "data_source_status":
        ftshare = ftshare_status()
        providers: dict[str, Any] = {
            "ftshare": {
                "available": bool(ftshare.get("available")),
                "configured": bool(ftshare.get("configured")),
                "persistent": bool(ftshare.get("persistent")),
                "capabilities": ftshare_capabilities(),
                "index_kline": ftshare_index_kline_available(),
                "sdk_version": ftshare.get("sdk_version"),
                "contracts": ftshare.get("contracts", {}),
                "optional_capabilities": ["minute_candles", "news", "market_data", "company_data"],
            }
        }
        try:
            from tools.free_sources import free_source_status as _builtin_free_status  # noqa: PLC0415

            providers["builtin_free"] = _builtin_free_status()
        except Exception:  # noqa: BLE001
            providers["builtin_free"] = {"available": False, "source": "builtin_free"}
        return {"ok": True, "external_rows": True, "providers": providers}
    if name == "configure_ftshare":
        return configure_ftshare_api_key(
            args.get("api_key"),
            test_connection=bool(args.get("test_connection", True)),
            persist=bool(args.get("persist", True)),
        )
    if name == "test_ftshare_connection":
        return test_ftshare_connection()
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

    def _authorized(self) -> bool:
        expected = self.server.auth_token  # type: ignore[attr-defined]
        provided = self.headers.get("X-DSH-Kline-Token", "")
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        return bool(expected and host in {"127.0.0.1", "localhost"} and hmac.compare_digest(provided, expected))

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/healthz":
            self._send_json({"ok": True, "service": "dsh_kline_chart", "version": SERVER_VERSION})
            return
        if not self._authorized():
            self._send_json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
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
        if not self._authorized():
            self._send_json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
            return
        if not path.startswith("/api/tools/"):
            self._send_json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._send_json({"ok": False, "error": "unsupported_media_type"}, status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
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

    def __init__(self, address: tuple[str, int], store: ChartSessionStore, auth_token: str) -> None:
        self.session_store = store
        self.auth_token = auth_token
        super().__init__(address, ChartRequestHandler)


class ChartService:
    def __init__(self, host: str, port: int) -> None:
        self.store = ChartSessionStore()
        self.auth_token = secrets.token_urlsafe(32)
        self.httpd = ChartHTTPServer((host, port), self.store, self.auth_token)
        self.host = host
        self.port = int(self.httpd.server_address[1])
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="dsh-kline-chart", daemon=True)
        self.thread.start()

    def publish(self, payload: dict[str, Any]) -> tuple[str, str]:
        token = self.store.create(payload)
        service_url = f"http://{self.host}:{self.port}"
        _write_runtime_session(token, service_url, self.auth_token, payload)
        return token, service_url


def _write_runtime_session(token: str, service_url: str, service_token: str, payload: dict[str, Any]) -> None:
    RUNTIME_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    document = {
        "ok": True,
        "process_id": os.getpid(),
        "host_process_id": HOST_PROCESS_ID,
        "session": token,
        "service_url": service_url,
        "service_token": service_token,
        "symbol": str(payload.get("symbol") or ""),
        "name": str(payload.get("name") or ""),
        "published_at": int(time.time()),
    }
    # Immutable, token-addressed snapshots survive MCP restarts. The host's
    # manifest is only a service locator, never the UI's chart selection.
    sessions_dir = RUNTIME_DIR / "sessions"
    sessions_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot = sessions_dir / f"{token}.json"
    _atomic_runtime_json(snapshot, {**document, "payload": payload})
    _atomic_runtime_json(RUNTIME_SESSION_FILE, document)


def _atomic_runtime_json(destination: Path, document: dict[str, Any]) -> None:
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix="chart-session-", suffix=".json", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, destination)
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


def start_chart_service() -> None:
    """Refresh only the service locator after restart; no chart is selected."""
    service = ensure_chart_service()
    _atomic_runtime_json(RUNTIME_SESSION_FILE, {
        "ok": True, "session": "", "process_id": os.getpid(),
        "host_process_id": HOST_PROCESS_ID,
        "service_url": f"http://{service.host}:{service.port}",
        "service_token": service.auth_token, "published_at": int(time.time()),
    })
