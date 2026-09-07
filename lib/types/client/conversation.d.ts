export interface ChartReference {
    session: string;
    order: number;
}
export interface Observable<T> {
    getSnapshot(): T;
    subscribe(listener: () => void): () => void;
}
export interface ConversationSnapshot {
    nodes?: readonly any[];
}
export interface SessionEventWindow {
    entries: readonly {
        type: string;
        event: any;
    }[];
}
export interface Sessions {
    list: Observable<{
        current?: string;
    }>;
    binding(id: string): {
        session: Observable<ConversationSnapshot>;
        eventSource?: Observable<SessionEventWindow>;
    } | undefined;
}
export declare function latestChartFromEvents(entries: SessionEventWindow['entries']): ChartReference | undefined;
export declare function latestChart(nodes: readonly any[]): ChartReference | undefined;
export declare function chartStorageKey(conversationId: string): string;
