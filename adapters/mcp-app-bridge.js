/* MCP Apps transport only. The shared DSH chart view is not modified on disk. */
(() => {
  const parentWindow = window.parent !== window ? window.parent : null;
  const pending = new Map();
  let sequence = 0;
  let frontendReady = false;
  let firstResult = true;
  let bufferedResult = null;
  let resolvePayload;
  let resolveHost;
  let rejectHost;
  const payloadReady = new Promise(resolve => { resolvePayload = resolve; });
  const hostReady = new Promise((resolve, reject) => { resolveHost = resolve; rejectHost = reject; });
  // The view waits on `ready` below; avoid an unhandled rejection before parsing ends.
  hostReady.catch(() => {});
  let hostContext = { displayMode: 'inline', availableDisplayModes: ['inline'] };
  // A detached host element separates host preferences from the view's own
  // overrides. The shared UI observes this, never its own theme mutations.
  const hostElement = document.createElement('div');
  const syncHostPreferences = () => {
    const locale = hostContext.locale || window.navigator?.language || 'en';
    const theme = hostContext.theme === 'dark' || hostContext.theme === 'light'
      ? hostContext.theme : (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    if (hostElement.lang !== locale) hostElement.lang = locale;
    if (hostElement.dataset.theme !== theme) hostElement.dataset.theme = theme;
  };
  syncHostPreferences();
  window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change', syncHostPreferences);
  document.documentElement.dataset.mcpApp = 'true';

  const post = message => parentWindow?.postMessage({ jsonrpc: '2.0', ...message }, '*');
  const requestHost = (method, params = {}, timeout = 120000) => new Promise((resolve, reject) => {
    if (!parentWindow) { reject(new Error('MCP Apps host is unavailable')); return; }
    const id = `dsh-kline-${++sequence}`;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`${method} timed out`));
    }, timeout);
    pending.set(id, { resolve, reject, timer });
    post({ id, method, params });
  });
  const callTool = (action, args = {}) => hostReady.then(() => requestHost('tools/call', {
    name: 'chart_action', arguments: { action, arguments: args },
  }));
  const deliverResult = value => {
    const payload = value?.structuredContent || value?.result?.structuredContent || value;
    if (!payload || !Array.isArray(payload.chartCommands)) return;
    window.__DSH_CHART_SESSION__ = payload;
    if (firstResult) { firstResult = false; resolvePayload(); }
    else if (frontendReady) Promise.resolve(window.handleToolResult({ structuredContent: payload })).catch(console.warn);
    else bufferedResult = payload;
  };
  const updateDisplayModeButton = () => {
    const button = document.getElementById('mcpDisplayModeBtn');
    if (!button) return;
    const expanded = hostContext.displayMode === 'fullscreen';
    const native = typeof window.openai?.requestDisplayMode === 'function';
    const modes = hostContext.availableDisplayModes || [];
    button.disabled = !native && !modes.includes(expanded ? 'inline' : 'fullscreen');
    const english = document.documentElement.lang.startsWith('en');
    button.title = expanded ? (english ? 'Close sidebar' : '收起侧边栏') : (english ? 'Open in sidebar' : '打开至侧边栏');
    if (button.disabled) button.title = english ? 'Expanded view is unavailable in this host' : '当前宿主不支持展开视图';
    button.setAttribute('aria-label', button.title);
    button.setAttribute('aria-expanded', String(expanded));
    button.classList.toggle('active', expanded);
  };
  window.__DSH_KLINE_MCP_APPS__ = {
    hostElement,
    ready: Promise.all([hostReady, payloadReady]), callTool, deliverResult, updateDisplayModeButton,
    async mounted() {
      frontendReady = true;
      if (bufferedResult) {
        const payload = bufferedResult;
        bufferedResult = null;
        await window.handleToolResult({ structuredContent: payload });
      }
    },
  };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input?.url || '';
    const match = url.match(/^\/dsh-kline\/api\/tools\/([^/?#]+)$/);
    if (!match) return nativeFetch(input, init);
    let args;
    try { args = init.body ? JSON.parse(init.body) : {}; } catch (error) { return Promise.reject(error); }
    return callTool(decodeURIComponent(match[1]), args).then(result => new Response(JSON.stringify(result || {}), {
      status: result?.isError || result?.structuredContent?.ok === false ? 400 : 200,
      headers: { 'Content-Type': 'application/json' },
    }));
  };
  window.addEventListener('message', event => {
    if (!parentWindow || event.source !== parentWindow) return;
    const message = event.data;
    if (!message || message.jsonrpc !== '2.0') return;
    if (pending.has(message.id) && ('result' in message || 'error' in message)) {
      const entry = pending.get(message.id);
      pending.delete(message.id);
      clearTimeout(entry.timer);
      if (message.error) entry.reject(new Error(message.error.message || 'Host request failed'));
      else entry.resolve(message.result);
      return;
    }
    if (message.method === 'ui/notifications/tool-result') deliverResult(message.params);
    if (message.method === 'ui/notifications/host-context-changed') {
      hostContext = { ...hostContext, ...message.params };
      syncHostPreferences();
      updateDisplayModeButton();
    }
    if (message.method === 'ui/resource-teardown' && message.id != null) {
      for (const entry of pending.values()) { clearTimeout(entry.timer); entry.reject(new Error('App closed')); }
      pending.clear();
      window.__DSH_KLINE_DISPOSED__ = true;
      post({ id: message.id, result: {} });
    }
  });
  const initialize = () => {
    updateDisplayModeButton();
    requestHost('ui/initialize', {
      protocolVersion: '2026-01-26',
      appInfo: { name: 'dsh-kline', version: '__DSH_KLINE_VERSION__' },
      appCapabilities: { availableDisplayModes: ['inline', 'fullscreen'] },
    }, 15000).then(result => {
      hostContext = { ...hostContext, ...result?.hostContext };
      syncHostPreferences();
      updateDisplayModeButton();
      post({ method: 'ui/notifications/initialized' });
      resolveHost();
    }).catch(rejectHost);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initialize, { once: true });
  else initialize();
  document.addEventListener('click', async event => {
    const button = event.target?.closest?.('#mcpDisplayModeBtn');
    if (!button || button.disabled) return;
    const mode = hostContext.displayMode === 'fullscreen' ? 'inline' : 'fullscreen';
    button.disabled = true;
    try {
      const result = typeof window.openai?.requestDisplayMode === 'function'
        ? await window.openai.requestDisplayMode({ mode })
        : await requestHost('ui/request-display-mode', { mode }, 15000);
      hostContext = { ...hostContext, ...result?.hostContext, displayMode: result?.mode || result?.displayMode || mode };
      updateDisplayModeButton();
    } catch (error) {
      updateDisplayModeButton();
      button.title = error.message;
      button.setAttribute('aria-label', error.message);
    }
  });
  if (window.MutationObserver) new MutationObserver(updateDisplayModeButton)
    .observe(document.documentElement, { attributes: true, attributeFilter: ['lang'] });
  if (window.ResizeObserver && parentWindow) {
    let lastHeight = -1;
    new ResizeObserver(() => {
      const height = document.documentElement.scrollHeight;
      if (height === lastHeight) return;
      lastHeight = height;
      post({ method: 'ui/notifications/size-changed', params: { height } });
    }).observe(document.documentElement);
  }
})();
