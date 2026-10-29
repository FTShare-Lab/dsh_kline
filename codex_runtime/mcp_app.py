"""MCP Apps resource assembly for the Codex Desktop chart."""
from __future__ import annotations

import base64
import json
from functools import lru_cache
from pathlib import Path

from .state import APP_RESOURCE_URI, MCP_APP_MIME

ROOT = Path(__file__).resolve().parents[1]
APP_META = {"ui": {"resourceUri": APP_RESOURCE_URI, "prefersBorder": False,
                    "csp": {"connectDomains": [], "resourceDomains": []}}}


def _bridge() -> str:
    """Return a standards-based ui/* bridge; no DSH loopback protocol is used."""
    return r'''<script>
(() => {
  const parent = window.parent === window ? null : window.parent;
  const pending = new Map(); let serial = 0, mounted = false, first = true, buffered = null;
  let resolvePayload, resolveHost, rejectHost;
  const payloadReady = new Promise(resolve => { resolvePayload = resolve; });
  const hostReady = new Promise((resolve, reject) => { resolveHost = resolve; rejectHost = reject; }); hostReady.catch(() => {});
  const appInstance = `ft-kline-${crypto.randomUUID()}`;
  let hostContext = { displayMode: 'inline', availableDisplayModes: ['inline'] };
  const hostElement = document.createElement('div');
  const post = message => parent?.postMessage({ jsonrpc: '2.0', ...message }, '*');
  const request = (method, params = {}, timeout = 60000) => new Promise((resolve, reject) => {
    if (!parent) return reject(new Error('MCP Apps host is unavailable'));
    const id = `ft-kline-${++serial}`;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out`)); }, timeout);
    pending.set(id, { resolve, reject, timer }); post({ id, method, params });
  });
  // Desktop hosts can attach the first tool result to ui/initialize, while
  // subsequent results arrive through ui/notifications/tool-result.  Consume
  // both shapes so the chart never waits forever for a notification that was
  // already delivered with initialization.
  const extractDelivery = value => {
    const pendingValues = [value]; const seen = new Set();
    while (pendingValues.length) {
      const current = pendingValues.shift();
      if (!current || (typeof current !== 'object' && !Array.isArray(current)) || seen.has(current)) continue;
      seen.add(current);
      const payload = current.chart_payload || current;
      if (Array.isArray(payload?.chartCommands)) {
        return { payload, candidate: current.candidate_chart_session || payload.candidate_chart_session };
      }
      for (const field of ['structuredContent', 'result', 'toolResult', 'toolOutput', 'params']) {
        if (current[field]) pendingValues.push(current[field]);
      }
    }
    return null;
  };
  const consumeDelivery = value => {
    const delivery = extractDelivery(value);
    return delivery ? deliver(delivery.payload, delivery.candidate) : Promise.resolve();
  };
  const action = (actionName, arguments_ = {}) => hostReady.then(() => request('tools/call', {
    name: 'ft_kline_app_action', arguments: { action: actionName, arguments: (() => {
      const contextRef = arguments_.context_ref || window.__DSH_CHART_SESSION__?.context_ref;
      return contextRef && actionName !== 'activate' ? { ...arguments_, context_ref: contextRef } : arguments_;
    })(), app_instance: appInstance },
  })).then(async result => {
    const value = result?.structuredContent || result?.result?.structuredContent || result;
    await consumeDelivery(result);
    return value;
  });
  const refreshObservation = async () => {
    const ref = window.__DSH_CHART_SESSION__?.context_ref;
    if (!ref) return null;
    const observed = await action('observe', { context_ref: ref });
    if (!observed?.ok) return observed;
    const key = String(observed.chart_session || '');
    window.__DSH_KLINE_OBSERVATION__ = { ok: true, context_ref: observed.context_ref, revision: observed.revision,
      source_status: { phase: 'aligned' }, observed_source_key: key };
    window.__DSH_KLINE_INITIAL_CHART_SESSION__ = key;
    window.__DSH_KLINE_SOURCE_KEY__ = () => key;
    return observed;
  };
  const deliver = async (payload, candidate) => {
    if (!payload || !Array.isArray(payload.chartCommands)) return;
    payload._live_chart_session = payload.chart_session || payload.source_chart_session;
    window.__DSH_CHART_SESSION__ = payload;
    // The first chart result is consumed before the shared chart view starts.
    // Preserve it as the active App-owned session before resolving readiness:
    // `init()` and the App-only bridge both read this exact object.  Resolving
    // first left the view visually populated but unable to claim its context,
    // so manual workbench actions failed with “no available chart session”.
    if (first) {
      first = false;
      window.__DSH_CHART_SESSION__ = payload;
      resolvePayload(payload);
      return;
    }
    if (!mounted) { buffered = { payload, candidate }; return; }
    await window.handleToolResult({ structuredContent: payload });
    await refreshObservation().catch(console.warn);
    if (candidate) await action('ack_render', { context_ref: payload.context_ref, candidate_chart_session: candidate, rendered: true }).catch(console.warn);
  };
  const sessionOnlyPresentation = () => {
    // The shared DSH view contains a persistent-key option. Remove it for
    // Codex rather than leaving a control that could imply disk storage.
    document.getElementById('ftsharePersistInput')?.closest('label')?.remove();
    const note = document.querySelector('#settingsSectionFtshare [data-i18n="ftshareConfigNote"]');
    if (note) note.textContent = document.documentElement.lang.startsWith('en')
      ? 'Codex uses this key only for the current App session. It is not shown or written to disk.'
      : 'Codex 仅在当前 App 会话使用此 Key，不显示也不写入磁盘。';
    const auto = document.querySelector('#settingsSectionSource .source-autoload span');
    if (auto) auto.textContent = document.documentElement.lang.startsWith('en')
      ? 'An environment FTSHARE_API_KEY takes priority. An App key lasts only for this open chart session.'
      : '环境变量 FTSHARE_API_KEY 优先；App 输入的 Key 仅在当前打开图表会话有效。';
  };
  window.__FT_KLINE_APP__ = { appInstance, ready: Promise.all([hostReady, payloadReady]), action, refreshObservation,
    async mounted() { mounted = true; sessionOnlyPresentation(); if (buffered) { const next = buffered; buffered = null; await deliver(next.payload, next.candidate); } await refreshObservation().catch(console.warn); } };
  window.__DSH_KLINE_REPORT_CONTEXT__ = () => { void refreshObservation().catch(console.warn); };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    const match = url.match(/^\/dsh-kline\/api\/tools\/([^/?#]+)$/);
    if (!match) return nativeFetch(input, init);
    let args = {}; try { args = init.body ? JSON.parse(init.body) : {}; } catch (error) { return Promise.reject(error); }
    let actionName = decodeURIComponent(match[1]);
    if (actionName === 'configure_ftshare') {
      const apiKey = String(args.api_key || '').trim();
      actionName = apiKey ? 'configure_session_key' : 'clear_session_key';
      args = apiKey ? { api_key: apiKey } : {};
    }
    return action(actionName, args).then(result => new Response(JSON.stringify(result || {}), {
      status: result?.ok === false ? 400 : 200, headers: { 'Content-Type': 'application/json' },
    }));
  };
  window.addEventListener('message', event => {
    if (!parent || event.source !== parent) return; const message = event.data;
    if (!message || message.jsonrpc !== '2.0') return;
    if (pending.has(message.id) && ('result' in message || 'error' in message)) {
      const item = pending.get(message.id); pending.delete(message.id); clearTimeout(item.timer);
      return message.error ? item.reject(new Error(message.error.message || 'Host request failed')) : item.resolve(message.result);
    }
    if (message.method === 'ui/notifications/tool-result') consumeDelivery(message.params).catch(console.warn);
    if (message.method === 'ui/notifications/host-context-changed') { hostContext = { ...hostContext, ...message.params }; hostElement.lang = hostContext.locale || navigator.language || 'en'; hostElement.dataset.theme = hostContext.theme || ''; }
    if (message.method === 'ui/resource-teardown' && message.id != null) {
      const ref = window.__DSH_CHART_SESSION__?.context_ref; if (ref) void action('close', { context_ref: ref }).catch(() => {});
      for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error('App closed')); } pending.clear();
      window.__DSH_KLINE_DISPOSED__ = true; post({ id: message.id, result: {} });
    }
  });
  const initialize = () => request('ui/initialize', { protocolVersion: '2026-01-26',
    appInfo: { name: 'ft-kline', version: '__FT_KLINE_VERSION__' }, appCapabilities: { availableDisplayModes: ['inline', 'fullscreen'] },
  }, 15000).then(async result => {
    hostContext = { ...hostContext, ...(result?.hostContext || {}) };
    hostElement.lang = hostContext.locale || navigator.language || 'en';
    await consumeDelivery(result);
    post({ method: 'ui/notifications/initialized' });
    resolveHost(result);
  }).catch(rejectHost);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true }); else initialize();
})();
</script>'''


@lru_cache(maxsize=1)
def mcp_app_html() -> str:
    html = (ROOT / "view" / "kline.html").read_text(encoding="utf-8")
    vendor = (ROOT / "view" / "vendor" / "klinecharts.min.js").read_text(encoding="utf-8").replace("</script>", "<\\/script>")
    html = html.replace('<script id="klinecharts-vendor" src="./vendor/klinecharts.min.js"></script>', f'<script id="klinecharts-vendor">{vendor}</script>')
    logo = ROOT / "view" / "ft-logo.jpg"
    if logo.exists(): html = html.replace("__FTV_LOGO_DATA__", "data:image/jpeg;base64," + base64.b64encode(logo.read_bytes()).decode("ascii"))
    version = str(json.loads((ROOT / "package.json").read_text(encoding="utf-8")).get("version") or "0.6.0")
    bridge = _bridge().replace("__FT_KLINE_VERSION__", version)
    marker = "init().catch((error) => {"
    if marker not in html: raise RuntimeError("chart view no longer exposes an MCP Apps initialization point")
    html = html.replace(marker, "window.__FT_KLINE_APP__.ready.then(() => init()).then(() => window.__FT_KLINE_APP__.mounted()).catch((error) => {", 1)
    return html.replace("</head>", bridge + "</head>", 1)


def register_resource(mcp) -> None:
    @mcp.resource(APP_RESOURCE_URI, name="ft_kline_chart_v2", title="FT K-Line", mime_type=MCP_APP_MIME, meta=APP_META)
    def chart_resource() -> str:
        return mcp_app_html()

