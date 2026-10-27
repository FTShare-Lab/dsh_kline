declare function source(raw: any): any;
declare function condition(raw: any): any;
export { source as sanitizePriceSource, condition as sanitizePriceCondition };
export declare function sanitizePriceSeriesCommand(raw: any, expectedBars: number, interval: string): any;
export declare function seriesObservation(raw: any): any;
