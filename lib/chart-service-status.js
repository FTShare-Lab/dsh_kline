import { readFile } from 'node:fs/promises';
export class ChartServiceUnavailable extends Error {
    reason;
    constructor(reason) { super(reason); this.reason = reason; }
}
export async function readServiceLocator(path, hostPid) {
    let saved;
    try {
        saved = JSON.parse(await readFile(path, 'utf8'));
    }
    catch (error) {
        const code = error && typeof error === 'object' && 'code' in error ? error.code : '';
        throw new ChartServiceUnavailable(code === 'ENOENT' ? 'service_locator_missing'
            : code === 'EACCES' || code === 'EPERM' ? 'service_locator_permission_denied' : 'service_locator_invalid');
    }
    if (!saved || typeof saved !== 'object' || Array.isArray(saved))
        throw new ChartServiceUnavailable('service_locator_invalid');
    const value = saved;
    if (value.host_process_id !== hostPid)
        throw new ChartServiceUnavailable('service_host_mismatch');
    if (value.ok !== true || typeof value.session !== 'string' || typeof value.service_url !== 'string'
        || typeof value.service_token !== 'string' || value.service_token.length < 32
        || !Number.isSafeInteger(value.process_id) || value.process_id <= 0
        || !Number.isSafeInteger(value.published_at) || value.published_at <= 0)
        throw new ChartServiceUnavailable('service_locator_invalid');
    try {
        const url = new URL(value.service_url);
        if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(url.hostname) || url.username || url.password)
            throw new Error();
    }
    catch {
        throw new ChartServiceUnavailable('service_locator_invalid');
    }
    try {
        process.kill(value.process_id, 0);
    }
    catch (error) {
        throw new ChartServiceUnavailable(error && typeof error === 'object' && 'code' in error && error.code === 'EPERM'
            ? 'backend_process_inaccessible' : 'backend_process_exited');
    }
    return value;
}
export async function probeChartService(locator, timeoutMs = 1500) {
    let response;
    try {
        response = await fetch(new URL('/healthz', locator.service_url), { signal: AbortSignal.timeout(timeoutMs) });
    }
    catch (error) {
        throw new ChartServiceUnavailable(error instanceof Error && error.name === 'TimeoutError' ? 'backend_timeout' : 'backend_unreachable');
    }
    let data;
    try {
        data = await response.json();
    }
    catch {
        throw new ChartServiceUnavailable('backend_invalid_health');
    }
    if (!response.ok || data?.ok !== true || data?.service !== 'dsh_kline_chart')
        throw new ChartServiceUnavailable('backend_invalid_health');
    // New locators attest a particular HTTP instance, preventing a reused PID or
    // port from making an unrelated process appear healthy. Old packages remain readable.
    if (locator.instance_id && (data.instance_id !== locator.instance_id || data.process_id !== locator.process_id
        || data.host_process_id !== locator.host_process_id))
        throw new ChartServiceUnavailable('backend_identity_mismatch');
}
export function unavailableService(reason = 'service_locator_missing') {
    const detail = {
        service_locator_missing: '尚未注册后端服务，请检查运行状态和启动日志。',
        service_locator_permission_denied: '无法读取服务定位文件，请检查运行目录权限。',
        service_locator_invalid: '服务定位文件损坏或格式无效，请检查启动日志。',
        service_host_mismatch: '服务定位记录不属于当前宿主，请重新加载插件。',
        backend_process_exited: '后端进程已退出，正在等待恢复，请检查启动日志。',
        backend_process_inaccessible: '无法检查后端进程，请检查进程访问权限。',
        backend_unreachable: '后端端口不可达，请检查启动日志。',
        backend_timeout: '后端响应超时，请稍后重试。',
        backend_invalid_health: '后端健康响应无效，请检查端口与启动日志。',
        backend_identity_mismatch: '后端实例与定位记录不一致，请重新加载插件。',
        runtime_preparing: '正在准备 Python 环境，请等待安装完成。',
        runtime_recovering: '后端正在恢复，请稍后重试并检查启动日志。',
    };
    return { ok: false, error: 'chart_session_unavailable', reason, message: `当前 DSH 的行情服务${detail[reason] || detail.service_locator_missing}` };
}
