export declare const inject: string[];
interface ClientContext {
    effect(callback: () => () => void, label: string): void;
}
declare global {
    interface Window {
        klinecharts?: any;
        __dshKlineVendorPromise?: Promise<any>;
        __dshKlineVwapRegistered?: boolean;
    }
}
export declare function apply(ctx: ClientContext): void;
export {};
