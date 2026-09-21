"""Application orchestration for fetched and caller-supplied K-line rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.analysis import analyze_rows
from services.rendering import render_analysis


FetchCandlesFn = Callable[..., dict[str, Any]]
ChartPayloadFn = Callable[..., dict[str, Any]]
ChartPublisherFn = Callable[[dict[str, Any]], tuple[str, str]]


@dataclass(frozen=True)
class AnalysisService:
    """Coordinate a data source, deterministic analysis, and optional host UI."""

    fetch_candles_fn: FetchCandlesFn
    chart_payload_fn: ChartPayloadFn | None = None
    publish_chart_fn: ChartPublisherFn | None = None

    def analyze_rows(self, rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        result = analyze_rows(rows, **kwargs)
        if self.chart_payload_fn is not None and self.publish_chart_fn is not None:
            try:
                payload = render_analysis(result, self.chart_payload_fn)
                session, _url = self.publish_chart_fn(payload)
                result.update(chart_session=session, chart_ready=bool(session), chart_service={"ok": True})
                result["chart"]["session_id"] = session
            except Exception as exc:  # noqa: BLE001
                result["chart_service"] = {"ok": False, "error": "chart_service_unavailable", "message": str(exc)}
        return result

    def analyze_symbol(
        self,
        symbol: str,
        *,
        resolved_name: str | None,
        interval: str,
        interval_value: int,
        session_count: int | None,
        limit: int,
        adjust: str,
        indicators: list[str] | None,
        metrics: list[str] | None,
        mark_support_resistance: bool,
        ma_periods: list[int] | None,
        rsi_period: int,
        boll_period: int,
        boll_std: float,
        volume_ma: int,
        atr_period: int,
    ) -> dict[str, Any]:
        requested = max(2, min(int(limit), 4000))
        fetch_limit = requested if interval == "minute" else min(4000, max(requested, int(requested * 1.8)))
        fetched = self.fetch_candles_fn(
            symbol,
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
            return {
                "ok": False,
                "error": "insufficient_candles",
                "message": "fewer than two candles",
                "symbol": symbol,
            }

        result = self.analyze_rows(
            rows,
            symbol=str(fetched.get("symbol") or symbol),
            name=str(fetched.get("name") or resolved_name or symbol),
            interval=interval,
            limit=requested,
            adjust=str(fetched.get("adjust") or adjust),
            indicators=indicators,
            metrics=metrics,
            mark_support_resistance=mark_support_resistance,
            ma_periods=ma_periods,
            rsi_period=rsi_period,
            boll_period=boll_period,
            boll_std=boll_std,
            volume_ma=volume_ma,
            atr_period=atr_period,
            data_source=str(fetched.get("source") or "ftshare"),
            data_source_url=None,
            security_workspace=None,
        )
        result.update(
            {
                "workflow": "fetch_analyze_chart_session",
                "provider_mode": "provider",
                "status": fetched.get("status"),
                "fetched_count": len(fetched.get("rows") or []),
                "history_warnings": fetched.get("warnings", []),
                "as_of": fetched.get("as_of"),
                "freshness": fetched.get("freshness"),
            }
        )
        return result


__all__ = ["AnalysisService"]
