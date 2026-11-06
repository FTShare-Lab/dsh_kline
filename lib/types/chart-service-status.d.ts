export declare class ChartServiceUnavailable extends Error {
    readonly reason: string;
    constructor(reason: string);
}
export interface ServiceLocator extends Record<string, unknown> {
    ok: true;
    process_id: number;
    host_process_id: number;
    session: string;
    service_url: string;
    service_token: string;
    published_at: number;
    instance_id?: string;
}
export declare function readServiceLocator(path: string, hostPid: number): Promise<ServiceLocator>;
export declare function probeChartService(locator: ServiceLocator, timeoutMs?: number): Promise<void>;
export declare function unavailableService(reason?: string): {
    ok: boolean;
    error: string;
    reason: string;
    message: string;
};
