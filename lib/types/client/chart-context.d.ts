export declare const CONTEXT_PUBLICATION_TIMEOUT_MS = 8000;
interface Options {
    conversationId?: string;
    capture: () => any;
    isActive: () => boolean;
    transport?: (body: any, signal?: AbortSignal) => Promise<any>;
    viewId?: string;
    publicationTimeoutMs?: number;
    apply?: (payload: any, token: string) => any;
    confirm?: (token: string) => void;
    feedback?: () => any;
    captureSource?: () => any;
    bindSource?: (token: string, previous: string | null) => void;
    confirmSource?: (token: string, confirmed: boolean) => void;
    onSourceStatus?: (status: any) => void;
    onPublished?: (publication: any) => void;
}
export declare function createChartContextPublisher(options: Options): {
    notify(): void;
    retrySource(): void;
    dispose(): void;
};
export {};
