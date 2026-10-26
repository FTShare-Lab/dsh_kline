export declare function text(value: unknown, max?: number): string;
/** Describes browser input -> display only, never vendor-native history or edit authority. */
export declare function sanitizeDataProvenance(raw: any): any;
export declare function sanitizeChartContext(raw: any): any;
export declare function observationKey(raw: any): string;
/** Identity required for editing the current source, excluding transient UI state. */
export declare function drawingSourceKey(raw: any): string;
export declare function drawingInventory(payload: any): any[];
