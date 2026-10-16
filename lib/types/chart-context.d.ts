export { sanitizeChartContext } from './chart-observation.ts';
export declare const CONTEXT_TTL_MS = 30000;
export declare class ChartContextBroker {
    private records;
    private queue;
    private directory;
    private now;
    private applications?;
    private sources?;
    constructor(directory: string, now?: () => number, runtime?: string);
    publish(raw: any): Promise<any>;
    private accept;
    prompt(context: any): string;
}
