"""Generic MCP Apps adapter for the Codex-hosted K-line view.

The UI is deliberately host-neutral.  DeepSeek Harness keeps using its own
sidebar/session bridge, while MCP Apps receives the same chart payload through
the MCP Apps resource and message bridge.
"""

from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path
from mcp import types


MCP_APP_RESOURCE_URI = "ui://dsh-kline/kline"
MCP_APP_RESOURCE_MIME = "text/html;profile=mcp-app"

# MCP Apps standard metadata.  The OpenAI-compatible outputTemplate key is
# included as a harmless compatibility alias for hosts that still use it.
MCP_APP_UI_META = {
    "ui": {
        "resourceUri": MCP_APP_RESOURCE_URI,
        "prefersBorder": False,
        "csp": {"connectDomains": [], "resourceDomains": []},
    },
    "openai/outputTemplate": MCP_APP_RESOURCE_URI,
}


def _bridge_script() -> str:
    source = Path(__file__).with_name("mcp-app-bridge.js").read_text(encoding="utf-8")
    return "<script>" + source + "</script>"


@lru_cache(maxsize=1)
def mcp_app_html() -> str:
    root = Path(__file__).resolve().parents[1]
    html = (root / "view" / "kline.html").read_text(encoding="utf-8")
    # Inject host controls at render time: keep the upstream DSH HTML byte-identical.
    controls = '<div class="header-controls">'
    init = 'init().catch((error) => {'
    if controls not in html or init not in html:
        raise RuntimeError("upstream chart view no longer exposes the MCP Apps integration points")
    button = '''<button class="btn mcp-app-only mcp-display-mode-btn" id="mcpDisplayModeBtn" type="button" title="打开至侧边栏" aria-label="打开至侧边栏" aria-expanded="false"><span class="icon-glyph" aria-hidden="true"><svg viewBox="0 0 24 24" focusable="false"><rect x="3.5" y="4" width="17" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M15 4v16M17 9l3 3-3 3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg></span></button>'''
    html = html.replace(controls, controls + button, 1)
    host_element = 'return globalThis.document?.documentElement || null;'
    host_language = 'function hostLanguage() {'
    if host_element not in html or host_language not in html:
        raise RuntimeError("upstream chart view no longer exposes host preference integration points")
    html = html.replace(host_element, 'return window.__DSH_KLINE_MCP_APPS__.hostElement;', 1)
    language_start = html.index(host_language)
    language_end = html.index('function hostTheme() {', language_start)
    html = (html[:language_start] + 'function hostLanguage() {\n  return /^zh(?:-|$)/i.test(hostDocumentElement().lang) ? "zh" : "en";\n}\n' + html[language_end:])
    html = html.replace(init, 'window.__DSH_KLINE_MCP_APPS__.ready.then(() => init()).then(() => window.__DSH_KLINE_MCP_APPS__.mounted()).catch((error) => {', 1)
    html = html.replace('</head>', '''<style>
      .mcp-display-mode-btn { display: inline-grid; width: 30px; min-width: 30px; height: 30px; padding: 0; place-items: center; }
      .mcp-display-mode-btn .icon-glyph { width: 17px; height: 17px; }
      .mcp-display-mode-btn.active svg { transform: scaleX(-1); }
      .mcp-display-mode-btn:disabled { opacity: .5; cursor: default; }
    </style></head>''', 1)
    vendor = (root / "view" / "vendor" / "klinecharts.min.js").read_text(encoding="utf-8")
    package_version = "0.0.0"
    try:
        package_version = str(json.loads((root / "package.json").read_text(encoding="utf-8")).get("version") or package_version)
    except Exception:  # noqa: BLE001
        pass
    vendor = vendor.replace("</script>", "<\\/script>")
    html = html.replace(
        '<script id="klinecharts-vendor" src="./vendor/klinecharts.min.js"></script>',
        f'<script id="klinecharts-vendor">{vendor}</script>',
    )
    logo_path = root / "view" / "ft-logo.jpg"
    if logo_path.exists():
        logo_data = "data:image/jpeg;base64," + base64.b64encode(logo_path.read_bytes()).decode("ascii")
        html = html.replace("__FTV_LOGO_DATA__", logo_data)
    bridge = _bridge_script().replace("__DSH_KLINE_VERSION__", package_version)
    if "</head>" not in html:
        raise RuntimeError("view/kline.html is missing </head>")
    return html.replace("</head>", bridge + "</head>", 1)


def register_mcp_app(mcp) -> None:
    from services.chart_actions import dispatch

    @mcp.resource(
        MCP_APP_RESOURCE_URI, name="dsh_kline_chart_app", title="FtAI K-Line",
        mime_type=MCP_APP_RESOURCE_MIME,
        meta={"ui": {"prefersBorder": False, "csp": {"connectDomains": [], "resourceDomains": []}}},
    )
    def chart_resource() -> str:
        return mcp_app_html()

    @mcp.tool(name="chart_action", meta={"ui": {"resourceUri": MCP_APP_RESOURCE_URI, "visibility": ["app"]}})
    def chart_action(action: str, arguments: dict) -> types.CallToolResult:
        """Internal interactive chart action; intended only for MCP Apps UI."""
        if len(json.dumps(arguments).encode("utf-8")) > 8 * 1024 * 1024:
            payload = {"ok": False, "error": "request_too_large"}
        else:
            try:
                payload = dispatch(action, arguments)
            except Exception as exc:  # noqa: BLE001
                payload = {"ok": False, "error": "chart_action_failed", "message": str(exc)}
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="chart action complete" if payload.get("ok", True) else str(payload.get("error")))],
            structuredContent=payload, isError=payload.get("ok") is False,
        )


__all__ = ["MCP_APP_RESOURCE_MIME", "MCP_APP_RESOURCE_URI", "MCP_APP_UI_META", "mcp_app_html"]
