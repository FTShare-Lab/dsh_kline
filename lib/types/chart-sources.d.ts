/** Keep only renderer fields; never copy arbitrary metadata, URLs or provider secrets. */
export declare function sanitizeSourcePayload(raw: any, state: any): any;
interface SourceView {
    ref: string;
    conversation: string;
    view: string;
    revision: number;
    active: boolean;
    ambiguous: boolean;
    applyCapable: boolean;
    state: any;
}
export declare class ChartSources {
    private offers;
    private runtime;
    private now;
    constructor(runtime: string, now?: () => number);
    private proofPath;
    private read;
    private write;
    acknowledge(view: SourceView, receipt: any): Promise<any>;
    offer(view: SourceView, raw: any): Promise<any>;
    assess(view: SourceView, raw?: any): Promise<any>;
}
export {};
