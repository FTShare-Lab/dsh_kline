"""DSH and Codex host capabilities.

The application layer receives one of these adapters and never needs to know
which host is running it.  DSH-specific imports remain lazy so Codex startup
does not load or start the chart locator service.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable


ChartPayloadFn = Callable[..., dict[str, Any]]
ChartPublisherFn = Callable[[dict[str, Any]], tuple[str, str]]
ResultTransformFn = Callable[[dict[str, Any]], dict[str, Any]]


_BASE_INSTRUCTIONS = (
    "IMPORTANT workflow policy: For ordinary K-line requests, call analyze_kline exactly once. "
    "It performs one configured-source fetch, deterministic calculations, and returns one structured result. "
    "FTShare is optional: when another tool or application already has OHLCV rows, call analyze_kline_rows exactly once. "
    "Never call health, fetch_candles, or calc_metrics as a preflight or follow-up; never use shell, filesystem, scripts, "
    "web probes, or another chart generator for the same request. Do not switch providers or reconstruct market rows. "
    "If the provider rejects a symbol or interval, explain that error and stop; do not probe other symbols or substitute "
    "another interval unless the user explicitly asks. Use fetch_candles only when raw OHLCV rows are explicitly requested, "
    "and use calc_metrics only for caller-supplied rows. analyze_kline_rows accepts OHLCV rows from any user-selected data "
    "source without persisting provider state. Only calculate and annotate support and resistance when the user explicitly "
    "requests it: pass metrics including support_resistance or set mark_support_resistance=true. "
    "Report count, interval, latest, and indicator values exactly as returned; do not infer a different bar count from the "
    "selected timeframe. Keep support/resistance labels from the metrics, but describe whether each level is above or below "
    "the latest close instead of calling an above-price support a current support. Use data_source_status, configure_ftshare, "
    "or test_ftshare_connection only when the user explicitly asks to inspect or configure a data source. Use market_pulse "
    "for an explicit whole-market overview, and use security_intelligence for an explicit request about a mainland stock's "
    "sector linkage, capital flows, or trading events; neither tool replaces analyze_kline for chart analysis. "
    "Market data may be delayed, incomplete, or unavailable; results and indicators are informational and do not constitute investment advice."
)


def _dsh_chart_payload(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from tools.draw import draw_kline

    return draw_kline(*args, **kwargs)


def _dsh_publish_chart(payload: dict[str, Any]) -> tuple[str, str]:
    from chart_service import publish_chart

    return publish_chart(payload)


def _dsh_start() -> None:
    from chart_service import start_chart_service

    start_chart_service()


def _codex_result_transform(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the shared frontend command form without starting DSH services.

    The core contract intentionally exposes ``chart``/``chart_spec``.  The
    existing K-line view consumes the richer command stream, so the Codex
    adapter materializes that renderer payload at the host boundary.
    """
    chart = payload.get("chart")
    if not isinstance(chart, dict) or not isinstance(chart.get("rows"), list):
        return payload
    if isinstance(payload.get("chartCommands"), list):
        return payload
    from tools.draw import draw_kline

    from services.rendering import render_analysis

    rendered = render_analysis(payload, draw_kline)
    transformed = {**rendered, **payload}
    transformed.update({
        "chartCommands": rendered.get("chartCommands", []),
        "chart_ui": {
            "ready": True,
            "mode": "mcp_apps",
            "resource_uri": "ui://dsh-kline/kline",
        },
    })
    return transformed


@dataclass(frozen=True)
class HostAdapter:
    name: str
    instructions: str
    chart_payload_fn: ChartPayloadFn | None
    publish_chart_fn: ChartPublisherFn | None
    result_transform_fn: ResultTransformFn | None = None
    start_fn: Callable[[], None] | None = None
    register_fn: Callable[[Any], None] | None = None
    chart_tool_meta: dict[str, Any] | None = None

    def start(self) -> None:
        if self.start_fn is not None:
            self.start_fn()


def dsh_adapter() -> HostAdapter:
    return HostAdapter(
        name="dsh",
        instructions=_BASE_INSTRUCTIONS + (
            " In DeepSeek Harness, say that the interactive chart is open in the right sidebar only when chart_ready is true; "
            "otherwise explain that the chart service is unavailable. Do not create files or claim that a chart was rendered based "
            "on a script or URL."
        ),
        chart_payload_fn=_dsh_chart_payload,
        publish_chart_fn=_dsh_publish_chart,
        result_transform_fn=None,
        start_fn=_dsh_start,
    )


def codex_adapter() -> HostAdapter:
    from adapters.mcp_apps import MCP_APP_UI_META, register_mcp_app

    return HostAdapter(
        name="codex",
        instructions=_BASE_INSTRUCTIONS + (
            " In Codex MCP Apps, chart_service_disabled is expected because no DSH chart service is used; "
            "when chart_ui.ready is true, report that the interactive chart is displayed in the MCP App and do not say the chart failed. "
            "The user can use the chart's Open in sidebar control to request fullscreen display mode."
        ),
        chart_payload_fn=None,
        publish_chart_fn=None,
        result_transform_fn=_codex_result_transform,
        register_fn=register_mcp_app,
        chart_tool_meta=MCP_APP_UI_META,
    )


def host_adapter_from_env(env: dict[str, str] | None = None) -> HostAdapter:
    values = os.environ if env is None else env
    name = str(values.get("DSH_KLINE_ADAPTER", "dsh")).strip().lower()
    if name not in {"dsh", "codex"}:
        raise ValueError("DSH_KLINE_ADAPTER must be dsh or codex")
    return codex_adapter() if name == "codex" else dsh_adapter()


__all__ = ["HostAdapter", "codex_adapter", "dsh_adapter", "host_adapter_from_env"]
