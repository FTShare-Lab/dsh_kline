import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { mountKlineView } from './generated-view';
export const inject = [];
const PANEL_MIN = 420;
const PANEL_MAX = 920;
const PANEL_DEFAULT = 680;
const SESSION_ENDPOINT = '/dsh-kline/session';
const STORAGE_KEY = 'dsh-kline:sidebar:v1';
const CURRENT_VERSION = '0.1.4';
const LATEST_RELEASE_URL = 'https://api.github.com/repos/FTShare-Lab/dsh_kline/releases/latest';
function isSymbolLikeName(value, symbol) {
    const text = String(value ?? '').trim();
    const normalizedSymbol = String(symbol ?? '').trim().toUpperCase();
    if (!text)
        return true;
    if (normalizedSymbol && text.toUpperCase() === normalizedSymbol)
        return true;
    const bareSymbol = normalizedSymbol.split('.', 1)[0];
    return text.toUpperCase() === bareSymbol;
}
export function apply(ctx) {
    ctx.effect(() => {
        installStyles();
        const host = document.createElement('div');
        host.dataset.dshKlineSidebar = '';
        document.body.appendChild(host);
        const root = createRoot(host);
        root.render(_jsx(KlineSidebar, {}));
        return () => {
            root.unmount();
            host.remove();
            document.getElementById('dsh-kline-sidebar-styles')?.remove();
            document.documentElement.style.removeProperty('--dsh-kline-sidebar-width');
        };
    }, 'dsh-kline: sidebar mount');
}
function KlineSidebar() {
    const [state, setState] = useState(readState);
    const [session, setSession] = useState();
    const [available, setAvailable] = useState(true);
    const [update, setUpdate] = useState();
    const drag = useRef();
    const compact = useCompactLayout();
    const panelWidth = compact ? window.innerWidth : state.width;
    const reservedWidth = state.open && !compact ? panelWidth : 0;
    useEffect(() => {
        document.documentElement.style.setProperty('--dsh-kline-sidebar-width', `${reservedWidth}px`);
        writeState(state);
    }, [reservedWidth, state]);
    useEffect(() => {
        let active = true;
        let timer;
        const refresh = async () => {
            try {
                const response = await fetch(SESSION_ENDPOINT, { cache: 'no-store' });
                const payload = await response.json();
                if (!active)
                    return;
                if (response.ok && payload.ok === true && typeof payload.session === 'string') {
                    setSession(payload);
                    setAvailable(true);
                }
                else {
                    setAvailable(response.ok);
                }
            }
            catch {
                if (active)
                    setAvailable(false);
            }
            finally {
                if (active)
                    timer = window.setTimeout(refresh, 1200);
            }
        };
        void refresh();
        return () => {
            active = false;
            if (timer !== undefined)
                window.clearTimeout(timer);
        };
    }, []);
    useEffect(() => {
        let active = true;
        void checkForUpdate().then(result => {
            if (active)
                setUpdate(result);
        });
        return () => {
            active = false;
        };
    }, []);
    const setOpen = (open) => setState(current => ({ ...current, open }));
    return (_jsxs(_Fragment, { children: [_jsx("button", { type: "button", className: `dsh-kline-rail ${state.open ? 'is-open' : ''}`, "aria-label": state.open ? '收起 K 线侧栏' : '打开 K 线侧栏', "aria-expanded": state.open, title: state.open ? '收起 K 线侧栏' : '打开 K 线侧栏', onClick: () => setOpen(!state.open), children: _jsx("span", { "aria-hidden": "true", children: "K" }) }), _jsxs("aside", { className: `dsh-kline-panel ${state.open ? '' : 'is-hidden'}`, style: { width: panelWidth }, "aria-label": "K \u7EBF\u5206\u6790\u4FA7\u680F", "aria-hidden": !state.open, children: [!compact && (_jsx("div", { className: "dsh-kline-resize", role: "separator", "aria-label": "\u8C03\u6574 K \u7EBF\u4FA7\u680F\u5BBD\u5EA6", "aria-orientation": "vertical", "aria-valuemin": PANEL_MIN, "aria-valuemax": PANEL_MAX, "aria-valuenow": panelWidth, tabIndex: 0, onKeyDown: (event) => {
                            const next = keyboardWidth(event.key, state.width);
                            if (next === undefined)
                                return;
                            event.preventDefault();
                            setState(current => ({ ...current, width: next }));
                        }, onPointerDown: (event) => {
                            event.currentTarget.setPointerCapture(event.pointerId);
                            drag.current = { startX: event.clientX, startWidth: state.width };
                        }, onPointerMove: (event) => {
                            if (!event.currentTarget.hasPointerCapture(event.pointerId) || drag.current === undefined)
                                return;
                            const width = clampWidth(drag.current.startWidth + drag.current.startX - event.clientX);
                            setState(current => ({ ...current, width }));
                        }, onPointerUp: (event) => {
                            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                                event.currentTarget.releasePointerCapture(event.pointerId);
                            }
                            drag.current = undefined;
                        } })), _jsxs("header", { className: "dsh-kline-header", children: [_jsxs("div", { children: [_jsx("strong", { children: session?.name && !isSymbolLikeName(session.name, session.symbol) ? session.name : 'K 线分析' }), session?.symbol && _jsx("small", { children: session.symbol })] }), _jsx("button", { type: "button", "aria-label": "\u5173\u95ED K \u7EBF\u4FA7\u680F", title: "\u5173\u95ED", onClick: () => setOpen(false), children: "x" })] }), update && (_jsxs("div", { className: "dsh-kline-update", role: "status", children: [_jsxs("span", { children: ["\u53D1\u73B0\u65B0\u7248\u672C v", update.version] }), _jsx("a", { href: update.url, target: "_blank", rel: "noreferrer", children: "\u67E5\u770B\u66F4\u65B0" })] })), _jsx("div", { className: "dsh-kline-content", children: session ? (_jsx(NativeKlineApp, { session: session })) : (_jsxs("div", { className: "dsh-kline-empty", role: "status", children: [_jsx("strong", { children: available ? '暂无 K 线图' : '图表服务未连接' }), _jsx("span", { children: available ? '分析完成后将在此显示' : '请检查 dsh_kline MCP 状态' })] })) })] })] }));
}
async function checkForUpdate() {
    try {
        const response = await fetch(LATEST_RELEASE_URL, {
            cache: 'no-store',
            headers: { Accept: 'application/vnd.github+json' },
        });
        if (!response.ok)
            return undefined;
        const release = await response.json();
        const version = typeof release.tag_name === 'string' ? release.tag_name.replace(/^v/i, '') : '';
        const url = typeof release.html_url === 'string' ? release.html_url : '';
        if (release.prerelease === true || !url || !isNewerVersion(version, CURRENT_VERSION))
            return undefined;
        return { version, url };
    }
    catch {
        return undefined;
    }
}
function isNewerVersion(candidate, current) {
    const parse = (value) => {
        const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(value);
        return match ? match.slice(1).map(Number) : undefined;
    };
    const next = parse(candidate);
    const installed = parse(current);
    if (!next || !installed)
        return false;
    for (let index = 0; index < next.length; index += 1) {
        if (next[index] === installed[index])
            continue;
        return next[index] > installed[index];
    }
    return false;
}
function NativeKlineApp({ session }) {
    const host = useRef(null);
    const [error, setError] = useState('');
    useEffect(() => {
        let active = true;
        let dispose;
        Promise.all([
            fetch('/dsh-kline/data', { cache: 'no-store' }).then(response => response.json()),
            loadKlinecharts(),
        ]).then(([result, klinecharts]) => {
            if (!active || !host.current)
                return;
            if (!result?.ok || !result?.payload)
                throw new Error(result?.message || '图表会话不可用');
            const root = host.current.shadowRoot || host.current.attachShadow({ mode: 'open' });
            dispose = mountKlineView(root, result.payload, { klinecharts });
        }).catch(reason => active && setError(String(reason?.message || reason)));
        return () => {
            active = false;
            dispose?.();
        };
    }, [session.session]);
    return (_jsx("div", { className: "dsh-kline-native-host", ref: host, children: error && _jsx("div", { className: "dsh-kline-error", role: "alert", children: error }) }));
}
function loadKlinecharts() {
    const loaded = () => typeof window.klinecharts?.init === 'function' ? window.klinecharts : undefined;
    if (loaded())
        return Promise.resolve(loaded());
    if (window.__dshKlineVendorPromise)
        return window.__dshKlineVendorPromise;
    window.__dshKlineVendorPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = '/dsh-kline/vendor/klinecharts.min.js';
        script.async = true;
        script.dataset.dshKlineVendor = 'true';
        script.onload = () => loaded() ? resolve(loaded()) : reject(new Error('KLineCharts 已下载但没有正确初始化'));
        script.onerror = () => reject(new Error('KLineCharts 加载失败'));
        document.head.appendChild(script);
    }).catch(error => {
        window.__dshKlineVendorPromise = undefined;
        document.querySelector('script[data-dsh-kline-vendor="true"]')?.remove();
        throw error;
    });
    return window.__dshKlineVendorPromise;
}
function useCompactLayout() {
    const [compact, setCompact] = useState(() => window.innerWidth <= 900);
    useEffect(() => {
        const update = () => setCompact(window.innerWidth <= 900);
        window.addEventListener('resize', update);
        return () => window.removeEventListener('resize', update);
    }, []);
    return compact;
}
function keyboardWidth(key, width) {
    if (key === 'Home')
        return PANEL_MIN;
    if (key === 'End')
        return PANEL_MAX;
    if (key === 'ArrowLeft')
        return clampWidth(width - 20);
    if (key === 'ArrowRight')
        return clampWidth(width + 20);
    return undefined;
}
function clampWidth(width) {
    return Math.min(PANEL_MAX, Math.max(PANEL_MIN, Math.round(width)));
}
function readState() {
    try {
        const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
        return {
            open: typeof value.open === 'boolean' ? value.open : true,
            width: clampWidth(typeof value.width === 'number' ? value.width : PANEL_DEFAULT),
        };
    }
    catch {
        return { open: true, width: PANEL_DEFAULT };
    }
}
function writeState(state) {
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    }
    catch {
        // The sidebar remains functional when browser storage is unavailable.
    }
}
function installStyles() {
    if (document.getElementById('dsh-kline-sidebar-styles'))
        return;
    const style = document.createElement('style');
    style.id = 'dsh-kline-sidebar-styles';
    style.textContent = `
    :root { --dsh-kline-sidebar-width: 0px; }
    #root { margin-right: calc(var(--dsh-sidebar-width, 0px) + var(--dsh-kline-sidebar-width)); transition: margin-right .2s ease; }
    .dsh-kline-panel { position: fixed; z-index: 52; top: 0; right: var(--dsh-sidebar-width, 0px); bottom: 0; display: flex; box-sizing: border-box; max-width: 100vw; flex-direction: column; overflow: hidden; border-left: 1px solid var(--dsw-alias-border-l2, #d9dde5); color: var(--dsw-alias-label-primary, #172033); background: var(--dsw-specific-sidebar-fill, #fff); box-shadow: -8px 0 24px rgb(19 32 54 / 8%); transition: transform .2s ease, visibility 0s; }
    .dsh-kline-panel.is-hidden { visibility: hidden; pointer-events: none; transform: translateX(102%); transition: transform .2s ease, visibility 0s linear .2s; }
    .dsh-kline-header { display: flex; min-height: 54px; align-items: center; justify-content: space-between; gap: 12px; padding: 0 14px 0 18px; border-bottom: 1px solid var(--dsw-alias-border-l2, #d9dde5); background: var(--dsw-specific-sidebar-fill, #fff); }
    .dsh-kline-header > div { display: flex; min-width: 0; align-items: baseline; gap: 8px; }
    .dsh-kline-header strong { overflow: hidden; font-size: 14px; line-height: 20px; text-overflow: ellipsis; white-space: nowrap; }
    .dsh-kline-header small { color: var(--dsw-alias-label-tertiary, #7a8495); font-size: 11px; white-space: nowrap; }
    .dsh-kline-header button { display: inline-flex; width: 32px; height: 32px; align-items: center; justify-content: center; padding: 0; border: 0; border-radius: 6px; color: inherit; background: transparent; cursor: pointer; font: 20px/1 system-ui; }
    .dsh-kline-header button:hover { background: var(--dsw-alias-interactive-bg-hover, #eef1f5); }
    .dsh-kline-update { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 12px; padding: 7px 14px 7px 18px; border-bottom: 1px solid #f4c48d; color: #8a4b08; background: #fff8ef; font-size: 12px; }
    .dsh-kline-update a { color: #a65400; font-weight: 600; text-decoration: none; white-space: nowrap; }
    .dsh-kline-update a:hover { text-decoration: underline; }
    .dsh-kline-content { min-height: 0; flex: 1; overflow: hidden; background: #fff; }
    .dsh-kline-native-host { display: block; width: 100%; height: 100%; overflow: hidden; background: #fff; }
    .dsh-kline-native { display: flex; height: 100%; min-width: 340px; flex-direction: column; overflow: hidden; color: #20242b; background: #fff; font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .dsh-kline-tabs, .dsh-kline-toolbar { display: flex; flex: 0 0 auto; align-items: center; gap: 6px; padding: 7px 10px; overflow-x: auto; border-bottom: 1px solid #e7ebef; scrollbar-width: none; }
    .dsh-kline-tabs::-webkit-scrollbar, .dsh-kline-toolbar::-webkit-scrollbar { display: none; }
    .dsh-kline-tabs button, .dsh-kline-toolbar button { min-width: 42px; height: 30px; padding: 0 10px; border: 1px solid #dfe4ea; border-radius: 4px; color: #20242b; background: #f7f9fb; cursor: pointer; white-space: nowrap; }
    .dsh-kline-tabs button { border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; font-weight: 600; }
    .dsh-kline-tabs button.active { border-bottom-color: #ff6b00; color: #20242b; }
    .dsh-kline-toolbar button.active { border-color: #ff6b00; color: #fff; background: #ff6b00; }
    .dsh-kline-toolbar button:focus-visible, .dsh-kline-tabs button:focus-visible { outline: 2px solid #4d6bfe; outline-offset: 1px; }
    .dsh-kline-toolbar-separator { width: 1px; height: 22px; flex: 0 0 1px; margin: 0 2px; background: #dfe4ea; }
    .dsh-kline-indicators { padding-top: 5px; padding-bottom: 5px; }
    .dsh-kline-chart-shell { position: relative; min-height: 320px; flex: 1 1 auto; overflow: hidden; }
    .dsh-kline-chart { width: 100%; height: 100%; min-height: 320px; }
    .dsh-kline-loading { position: absolute; z-index: 2; inset: 0; display: grid; place-items: center; color: #677286; background: rgb(255 255 255 / 78%); }
    .dsh-kline-error { flex: 0 0 auto; padding: 7px 12px; color: #b42318; background: #fff1f0; }
    .dsh-kline-levels { display: flex; flex: 0 0 auto; gap: 6px; padding: 6px 10px; overflow-x: auto; border-top: 1px solid #e7ebef; scrollbar-width: none; }
    .dsh-kline-levels span { padding: 2px 6px; border-radius: 3px; color: #516070; background: #f1f4f7; white-space: nowrap; }
    .dsh-kline-pane-empty { display: grid; height: 100%; place-items: center; color: #7a8495; }
    .dsh-kline-news, .dsh-kline-overview { min-height: 0; flex: 1; overflow-y: auto; padding: 12px 16px 24px; }
    .dsh-kline-news article { padding: 12px 0; border-bottom: 1px solid #e7ebef; }
    .dsh-kline-news article > div { display: flex; align-items: baseline; gap: 8px; }
    .dsh-kline-news article span { flex: 0 0 auto; padding: 1px 5px; border-radius: 3px; color: #b54708; background: #fff3e8; font-size: 11px; }
    .dsh-kline-news a, .dsh-kline-news strong { color: #20242b; font-weight: 650; text-decoration: none; }
    .dsh-kline-news a:hover { color: #ff6b00; }
    .dsh-kline-news time, .dsh-kline-news p, .dsh-kline-overview p, .dsh-kline-news footer, .dsh-kline-overview footer { color: #7a8495; }
    .dsh-kline-news time { display: block; margin-top: 5px; font-size: 11px; }
    .dsh-kline-news p { margin: 7px 0 0; }
    .dsh-kline-overview h3 { margin: 0 0 12px; font-size: 17px; }
    .dsh-kline-facts, .dsh-kline-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-bottom: 14px; }
    .dsh-kline-facts > div, .dsh-kline-metrics > div { min-width: 0; padding: 9px 10px; border: 1px solid #e7ebef; border-radius: 4px; }
    .dsh-kline-facts span, .dsh-kline-metrics span { display: block; color: #7a8495; font-size: 11px; }
    .dsh-kline-facts strong, .dsh-kline-metrics strong { display: block; overflow: hidden; margin-top: 3px; text-overflow: ellipsis; white-space: nowrap; }
    .dsh-kline-overview dl { margin: 0; }
    .dsh-kline-overview dl > div { display: grid; grid-template-columns: minmax(90px, 30%) 1fr; gap: 12px; padding: 8px 0; border-bottom: 1px solid #edf0f4; }
    .dsh-kline-overview dt { color: #7a8495; }
    .dsh-kline-overview dd { margin: 0; overflow-wrap: anywhere; }
    .dsh-kline-news footer, .dsh-kline-overview footer { margin-top: 14px; padding-top: 10px; border-top: 1px solid #e7ebef; font-size: 11px; }
    .dsh-kline-empty { display: flex; height: 100%; align-items: center; justify-content: center; flex-direction: column; gap: 6px; color: var(--dsw-alias-label-tertiary, #7a8495); text-align: center; }
    .dsh-kline-empty strong { color: var(--dsw-alias-label-secondary, #505b6c); font-size: 14px; }
    .dsh-kline-empty span { font-size: 12px; }
    .dsh-kline-rail { position: fixed; z-index: 53; top: 50%; right: calc(var(--dsh-sidebar-width, 0px) + var(--dsh-kline-sidebar-width) + 10px); display: inline-flex; width: 32px; height: 88px; align-items: center; justify-content: center; padding: 0; border: 1px solid var(--dsw-alias-border-l2, #d9dde5); border-radius: 6px; color: var(--dsw-alias-label-primary, #172033); background: var(--dsw-specific-sidebar-fill, #fff); box-shadow: 0 4px 14px rgb(19 32 54 / 10%); cursor: pointer; transform: translateY(-50%); transition: right .2s ease; }
    .dsh-kline-rail span { font: 700 13px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
    .dsh-kline-rail:hover { background: var(--dsw-alias-interactive-bg-hover, #eef1f5); }
    .dsh-kline-resize { position: absolute; z-index: 3; top: 0; bottom: 0; left: -4px; width: 8px; cursor: col-resize; touch-action: none; }
    .dsh-kline-resize:hover, .dsh-kline-resize:focus-visible { background: var(--dsw-alias-interactive-bg-hover-accent, #4d6bfe); outline: 0; }
    @media (max-width: 900px) {
      #root { margin-right: var(--dsh-sidebar-width, 0px); }
      .dsh-kline-panel { right: 0; width: 100vw !important; }
      .dsh-kline-rail { top: 74px; right: 10px; width: 36px; height: 36px; transform: none; }
      .dsh-kline-rail.is-open { display: none; }
      .dsh-kline-chart-shell { min-height: 280px; }
      .dsh-kline-chart { min-height: 280px; }
    }
    @media (prefers-reduced-motion: reduce) { #root, .dsh-kline-panel, .dsh-kline-rail { transition: none; } }
  `;
    document.head.appendChild(style);
}
