import type { BetterSidebarService } from 'dsh-better-sidebar';
import type { Sessions } from './conversation';
export declare function BetterSidebarBridge({ service, sessions }: {
    service: BetterSidebarService;
    sessions: Sessions;
}): import("react").JSX.Element | null;
