export declare class ChartHttpError extends Error {
    readonly reason: 'timeout' | 'unreachable' | 'too_large' | 'invalid_url';
    constructor(reason: ChartHttpError['reason']);
}
/** Private loopback transport. Avoid the host's bundled fetch/Undici socket QoS path. */
export declare function requestChartHttp(input: string | URL, options: {
    method?: 'GET' | 'POST';
    headers?: Record<string, string>;
    body?: string;
    timeoutMs: number;
    maxBytes: number;
}): Promise<{
    status: number;
    body: Buffer;
}>;
