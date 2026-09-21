"""Shared UI actions for DSH HTTP and MCP Apps; no host lifecycle."""
from __future__ import annotations
from typing import Any, Callable
from types import SimpleNamespace
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
from tools.watchlist import get_watchlist_state, save_watchlist_state
from tools.fetch import (
    configure_ftshare_api_key,
    data_source_capability_contract,
    fetch_candles,
    fetch_comparison_candles,
    fetch_market_board_detail,
    fetch_market_ticker,
    fetch_market_pulse,
    fetch_security_workspace,
    fetch_security_intelligence,
    ftshare_capabilities,
    ftshare_index_kline_available,
    ftshare_status,
    search_symbols,
    symbol_directory,
    test_ftshare_connection,
)

CHART_API_ACTIONS = frozenset(
    {
        "analyze_kline",
        "analyze_key_levels",
        "calc_range",
        "fetch_candles",
        "fetch_comparison_candles",
        "fetch_security_workspace",
        "fetch_market_pulse",
        "fetch_market_board_detail",
        "fetch_security_intelligence",
        "watchlist_get",
        "watchlist_save",
        "market_ticker",
        "search_symbols",
        "symbol_directory",
        "data_source_status",
        "configure_ftshare",
        "test_ftshare_connection",
    }
)

PROVIDER_NAMES = ["symbol_directory","ftshare_status","ftshare_capabilities","ftshare_index_kline_available","data_source_capability_contract","configure_ftshare_api_key","test_ftshare_connection","get_watchlist_state","save_watchlist_state","fetch_candles","fetch_comparison_candles","fetch_security_workspace","fetch_market_pulse","fetch_market_board_detail","fetch_security_intelligence","fetch_market_ticker","search_symbols","calc_range"]

def _http_key_levels(args: dict[str, Any]) -> dict[str, Any]:
    """Analyze the displayed bars only; never fetch or replace market data."""
    from core.analysis import support_resistance_marks

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
    marks = [{"type": "TEXT_MARKER", **mark} for mark in support_resistance_marks(metrics)]
    return {"ok": True, "symbol": str(args.get("symbol") or ""),
            "count": len(rows), "chartCommands": marks, "metrics": metrics,
            "status": "ready" if marks else "no_levels"}


def _http_analyze_kline(args: dict[str, Any], *, fetch_fn=fetch_candles, search_fn=search_symbols) -> dict[str, Any]:
    """Redraw using the shared analysis service without publishing host sessions."""
    from services.analysis_service import AnalysisService
    from services.inputs import resolve_symbol_input, validate_interval

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
        normalized_interval, interval_error = validate_interval(str(args.get("interval") or "day"))
        if interval_error:
            return {"ok": False, **interval_error}
        interval = normalized_interval or "day"
        resolved_symbol, resolved_name, symbol_error = resolve_symbol_input(symbol, search_fn)
        if symbol_error:
            return {"ok": False, **symbol_error}
        adjust = str(args.get("adjust") or "none").strip().lower()
        if adjust not in {"none", "forward", "backward"}:
            adjust = "none"
        interval_value = int(_positive(args.get("interval_value"), 1, 1, 240))
        raw_sessions = args.get("session_count")
        session_count = int(_positive(raw_sessions, 5, 1, 10)) if raw_sessions is not None else None
        requested = max(2, min(int(args.get("limit") or 60), 4000))
        boll_period = int(_positive(args.get("boll_period"), DEFAULT_BOLL_PERIOD, 2, 200))
        boll_std = float(_positive(args.get("boll_std"), DEFAULT_BOLL_STD, 0.5, 5.0))
        rsi_period = int(_positive(args.get("rsi_period"), DEFAULT_RSI_PERIOD, 2, 100))
        atr_period = int(_positive(args.get("atr_period"), DEFAULT_ATR_PERIOD, 2, 100))
        volume_ma = int(_positive(args.get("volume_ma"), DEFAULT_VOLUME_MA, 2, 200))
        service = AnalysisService(fetch_candles_fn=lambda *call_args, **call_kwargs: fetch_fn(*call_args, **call_kwargs))
        result = service.analyze_symbol(
            resolved_symbol or symbol,
            resolved_name=resolved_name,
            interval=interval,
            interval_value=interval_value,
            session_count=session_count,
            limit=requested,
            adjust=adjust,
            indicators=args.get("indicators"),
            metrics=args.get("metrics") if isinstance(args.get("metrics"), list) else None,
            mark_support_resistance=bool(args.get("mark_support_resistance")),
            ma_periods=args.get("ma_periods"),
            rsi_period=rsi_period,
            boll_period=boll_period,
            boll_std=boll_std,
            volume_ma=volume_ma,
            atr_period=atr_period,
        )
        if not result.get("ok"):
            return dict(result)
        chart = result.get("chart") or {}
        rows = list(chart.get("rows") or [])
        payload = draw_kline(
            rows,
            indicators=chart.get("indicators"),
            indicators_explicit=args.get("indicators") is not None,
            ma_periods=chart.get("ma_periods"),
            marks=chart.get("marks"),
            symbol=str(result.get("symbol") or resolved_symbol or symbol),
            name=str(result.get("name") or resolved_name or symbol),
            data_source=str(result.get("source") or "ftshare"),
            interval=interval,
            boll_period=boll_period,
            boll_std=boll_std,
            volume_ma=volume_ma,
            rsi_period=rsi_period,
            atr_period=atr_period,
        )
        payload.update(
            {
                "ok": True,
                "workflow": "chart_api_analyze_key_levels",
                "adjust": result.get("adjust") or adjust,
                "source": result.get("source") or "ftshare",
                "count": result.get("count"),
                "fetched_count": result.get("fetched_count"),
                "latest": result.get("latest"),
                "metrics": result.get("metrics"),
                "warnings": result.get("warnings", []),
            }
        )
        return payload
    except TypeError as exc:
        return {"ok": False, "error": "invalid_arguments", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "chart_action_failed", "message": str(exc)}


def dispatch(name: str, args: dict[str, Any], *, providers=None) -> dict[str, Any]:
    if name not in CHART_API_ACTIONS:
        return {"ok": False, "error": "unsupported_chart_action", "message": f"unsupported action: {name}"}
    api = SimpleNamespace(**{key: (providers or {}).get(key, globals()[key]) for key in PROVIDER_NAMES})
    if name == "analyze_key_levels":
        return _http_key_levels(args)
    if name == "analyze_kline":
        return _http_analyze_kline(args, fetch_fn=api.fetch_candles, search_fn=api.search_symbols)
    if name == "symbol_directory":
        return api.symbol_directory(force_refresh=bool(args.get("refresh") or args.get("force_refresh")))
    if name == "data_source_status":
        ftshare = api.ftshare_status()
        providers: dict[str, Any] = {
            "ftshare": {
                "available": bool(ftshare.get("available")),
                "configured": bool(ftshare.get("configured")),
                "persistent": bool(ftshare.get("persistent")),
                "credential_source": ftshare.get("credential_source", "none"),
                "can_clear": bool(ftshare.get("can_clear")),
                "capabilities": api.ftshare_capabilities(),
                "index_kline": api.ftshare_index_kline_available(),
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
        return {"ok": True, "external_rows": True, "providers": providers, "capability_contract": api.data_source_capability_contract()}
    if name == "configure_ftshare":
        return api.configure_ftshare_api_key(
            args.get("api_key"),
            test_connection=bool(args.get("test_connection", True)),
            persist=bool(args.get("persist", True)),
        )
    if name == "test_ftshare_connection":
        return api.test_ftshare_connection()
    if name == "watchlist_get":
        return {"ok": True, "watchlist": api.get_watchlist_state()}
    if name == "watchlist_save":
        return api.save_watchlist_state(args.get("watchlist"))
    routes: dict[str, Callable[..., dict[str, Any]]] = {
        "fetch_candles": api.fetch_candles,
        "fetch_comparison_candles": api.fetch_comparison_candles,
        "fetch_security_workspace": api.fetch_security_workspace,
        "fetch_market_pulse": api.fetch_market_pulse,
        "fetch_market_board_detail": api.fetch_market_board_detail,
        "fetch_security_intelligence": api.fetch_security_intelligence,
        "market_ticker": api.fetch_market_ticker,
        "search_symbols": api.search_symbols,
        "calc_range": api.calc_range,
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
