interface Options {
    conversationId?: string;
    viewId: string;
    capture: () => any;
    isActive: () => boolean;
    apply: (payload: any, token: string) => any;
    confirm?: (token: string) => void;
}
export declare function createChartApplyController(options: Options): {
    consume(command: any, publication: any): any;
    confirm(ack: any): void;
};
export {};
