/** Canonical explicit labeled paths: no sorting, snapping or automatic waves. */
export interface LabeledPolylinePoint {
    label: string;
    time: number;
    price: number;
}
export declare function sanitizePolylinePoints(raw: any): LabeledPolylinePoint[];
export declare function polylineOverlayPoints(command: any): {
    timestamp: number;
    value: number;
}[];
