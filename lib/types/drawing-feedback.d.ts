export declare const FEEDBACK_KINDS: string[];
export declare const FEEDBACK_STATUSES: string[];
export declare const FEEDBACK_REASONS: string[];
export declare function sanitizeDrawingFeedback(raw: any, allowed: any[]): any;
export declare function collectDrawingFeedback(payload: any, context: any, chart: any, previous?: any[], phase?: string): any;
