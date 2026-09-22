import type { BetterSidebarService } from 'dsh-better-sidebar';
export declare const KLINE_TAB_ID = "ftshare-kline:chart";
export declare const KLINE_TAB_TITLE_ZH = "FT K-Line \u00B7 \u975E\u51F8K\u7EBF\u52A9\u624B";
export declare const KLINE_TAB_TITLE_EN = "FT K-Line \u00B7 \u975E\u51F8K\u7EBF\u52A9\u624B";
export declare function klineTabTitle(locale?: string): string;
export declare function migrateKlineTabTitle(service: BetterSidebarService, tab: {
    id: string;
    type: string;
    title?: string;
}, sessionId?: string): void;
export declare function isSidebarUsable(service?: BetterSidebarService): boolean;
export declare function cleanClassicTabs(service: BetterSidebarService): () => void;
