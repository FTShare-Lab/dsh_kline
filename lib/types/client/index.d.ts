import type { Sessions } from './conversation';
export declare const inject: string[];
interface ClientContext {
    effect(callback: () => () => void, label?: string): void;
    inject(deps: string[], callback: (ctx: ClientContext) => void): unknown;
    get(name: string): unknown;
    sessions: Sessions;
}
export declare function apply(ctx: ClientContext): void;
export {};
