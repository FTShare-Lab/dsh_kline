export interface ChartSession {
    ok: true;
    session: string;
    symbol?: string;
    name?: string;
    published_at: number;
}
export interface ChartIdentity {
    symbol?: string;
    name?: string;
}
export declare function standaloneChartSession(conversationId?: string): string;
export declare function standaloneWorkspaceScope(conversationId?: string): string;
export declare function isSymbolLikeName(value: string | undefined, symbol: string | undefined): boolean;
declare global {
    interface Window {
        klinecharts?: any;
        __dshKlineVendorPromise?: Promise<any>;
        __dshKlineVwapRegistered?: boolean;
    }
}
export declare function NativeKlineApp({ session, conversationId, onIdentity }: {
    session: ChartSession;
    conversationId: string;
    onIdentity: (symbol?: string, name?: string) => void;
}): import("react").JSX.Element;
export declare function StandaloneKlineApp({ conversationId, onIdentity }: {
    conversationId: string;
    onIdentity: (symbol?: string, name?: string) => void;
}): import("react").JSX.Element;
