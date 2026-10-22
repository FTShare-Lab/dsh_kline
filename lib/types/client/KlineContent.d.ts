import { type KlineHostProps } from './embed';
export interface ChartSession {
    ok: true;
    session: string;
    symbol?: string;
    name?: string;
    published_at: number;
    recovery?: boolean;
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
export declare function NativeKlineApp({ session, conversationId, ownerConversationId, visible, onIdentity }: {
    session: ChartSession;
    conversationId: string;
    ownerConversationId?: string;
    visible?: boolean;
    onIdentity: (symbol?: string, name?: string) => void;
}): import("react").JSX.Element;
export type { KlineChrome, KlineHostProps, KlineEmbedApi } from './embed';
export declare function StandaloneKlineApp({ conversationId, ownerConversationId, visible, onIdentity, embedded, chrome, theme, symbol, name }: {
    conversationId: string;
    ownerConversationId?: string;
    visible?: boolean;
    onIdentity: (symbol?: string, name?: string) => void;
} & KlineHostProps): import("react").JSX.Element;
