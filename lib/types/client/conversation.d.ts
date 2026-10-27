export interface ChartReference {
    session: string;
    order: number;
    recovery?: boolean;
    recoverySourceSessions?: string[];
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
export interface SessionListSnapshot {
    current?: string;
    byId?: Record<string, {
        retainedBy?: {
            mainView?: number;
        };
    }>;
}
export interface Sessions {
    list: Observable<SessionListSnapshot>;
    binding(id: string): {
        session: Observable<ConversationSnapshot>;
        eventSource?: Observable<SessionEventWindow>;
    } | undefined;
}
/** Resolve one active conversation across the two public DSH session shapes. */
export declare function currentConversationId(snapshot: SessionListSnapshot): string | undefined;
export declare function latestChartFromEvents(entries: SessionEventWindow['entries']): ChartReference | undefined;
export declare function latestChart(nodes: readonly any[]): ChartReference | undefined;
export declare function chartStorageKey(conversationId: string): string;
