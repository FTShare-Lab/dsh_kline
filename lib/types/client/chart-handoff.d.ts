import { type ChartReference, type Sessions, type SessionEventWindow } from './conversation.ts';
/** Distinguish live appends from history hydration using the host's delta. */
export declare function observeLiveCharts(initial: SessionEventWindow): (window: SessionEventWindow) => ChartReference | undefined;
export declare function handoffLiveChart(sessions: Sessions, conversationId: string, reference: ChartReference): void;
export declare function liveChartFor(sessions: Sessions, conversationId?: string): ChartReference | undefined;
