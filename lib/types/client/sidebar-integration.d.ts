import type { BetterSidebarService } from 'dsh-better-sidebar';
export declare const KLINE_TAB_ID = "ftshare-kline:chart";
export declare function isSidebarUsable(service?: BetterSidebarService): boolean;
export declare function cleanClassicTabs(service: BetterSidebarService): () => void;
