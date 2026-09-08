import { type ChartReference, type Sessions } from './conversation';
export declare function useChartReference(sessions: Sessions, conversationId?: string, onNewChart?: (reference: ChartReference) => void): ChartReference | undefined;
