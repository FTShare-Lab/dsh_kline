export declare const FEEDBACK_KINDS: string[];
export declare const FEEDBACK_STATUSES: string[];
export declare const FEEDBACK_REASONS: string[];
export declare const CANVAS_VISIBILITIES: string[];
/** Plot-coordinate geometry only: labels, DOM occlusion and pixels are not verified. */
export declare function projectedCanvasVisibility(kind: string, command: any, expected: any, chart: any): string;
export declare function sanitizeDrawingFeedback(raw: any, allowed: any[]): any;
export declare function collectDrawingFeedback(payload: any, context: any, chart: any, previous?: any[], phase?: string): any;
