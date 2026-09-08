import type { BetterSidebarService } from 'dsh-better-sidebar';
export declare const defaultTabKey: (sessionId: string) => string;
export declare function installDefaultKlineTabs(service: BetterSidebarService, storage?: Pick<Storage, 'getItem' | 'setItem'>): () => void;
