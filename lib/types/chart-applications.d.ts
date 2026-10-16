export interface ApplicationView {
    ref: string;
    conversation: string;
    view: string;
    revision: number;
    active: boolean;
    ambiguous: boolean;
    applyCapable?: boolean;
    state: any;
}
export declare class ChartApplications {
    private runtime;
    private now;
    constructor(runtime: string, now?: () => number);
    private directory;
    private path;
    private read;
    private write;
    private recoveryPath;
    recover(conversation: string): Promise<any>;
    private validate;
    private candidate;
    private publicReceipt;
    acknowledge(view: ApplicationView, receipt: any): Promise<any>;
    dispatch(view: ApplicationView): Promise<any>;
}
