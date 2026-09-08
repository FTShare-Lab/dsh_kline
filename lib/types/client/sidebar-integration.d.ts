import type { BetterSidebarService } from 'dsh-better-sidebar';
export declare const KLINE_TAB_ID = "ftshare-kline:chart";
export declare const KLINE_TAB_TITLE = "\u975E\u51F8K\u7EBF\u52A9\u624B / dsh_kline";
export declare function migrateKlineTabTitle(service: BetterSidebarService, tab: {
    id: string;
    type: string;
    title?: string;
}, sessionId?: string): void;
export declare function isSidebarUsable(service?: BetterSidebarService): boolean;
export declare function cleanClassicTabs(service: BetterSidebarService): () => void;
